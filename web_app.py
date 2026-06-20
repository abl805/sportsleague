import contextlib
import hashlib
import io
import json
import os
import secrets

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None
if load_dotenv:
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import functools

from flask import Flask, flash, redirect, render_template, request, session, url_for, Response
from itsdangerous import BadSignature, URLSafeSerializer

from league import web_queries as q
from league.chatgpt_bridge import get_recent_interviews, save_interview_response
from league.database import create_tables, get_connection
from league.fan_experience import cast_poll_vote, publish_weekly_editorial
from league.offseason import (
    OFFSEASON_STAGE_LABELS,
    OFFSEASON_STAGES,
    advance_full_offseason_from_default_db,
    advance_offseason_from_default_db,
)
from league.trade_engine import execute_trade, invalidate_trade, validate_trade, veto_trade
from league.playoffs import get_bracket, get_playoff_snapshot
from run_week import run_week


app = Flask(__name__)
app.secret_key = os.environ.get("AIBA_SECRET_KEY", "aaibl-local-dev-console")


def _cookie_serializer():
    return URLSafeSerializer(app.secret_key, salt="aiba-fan-cookie")


def _signed_cookie_value(name):
    raw = request.cookies.get(name)
    if not raw:
        return None
    try:
        return _cookie_serializer().loads(raw)
    except BadSignature:
        return None


def _followed_team_id():
    value = _signed_cookie_value("aiba_followed_team")
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _fan_voter_hash():
    token = _signed_cookie_value("aiba_fan_token")
    if not token:
        token = secrets.token_urlsafe(24)
    digest = hashlib.sha256(f"{token}:{app.secret_key}".encode("utf-8")).hexdigest()
    return token, digest

def _commissioner_password():
    return os.environ.get("COMMISSIONER_PASSWORD", "")


def require_commissioner(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("is_commissioner"):
            return redirect(url_for("commissioner_login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


@app.route("/commissioner/login", methods=["GET", "POST"])
def commissioner_login():
    if request.method == "POST":
        pw = request.form.get("password", "")
        expected = _commissioner_password()
        if expected and pw == expected:
            session["is_commissioner"] = True
            dest = request.form.get("next") or url_for("commissioner")
            return redirect(dest)
        flash("Incorrect password.", "error")
    return render_template("commissioner_login.html",
                           next=request.args.get("next", url_for("commissioner")))


@app.route("/commissioner/logout")
def commissioner_logout():
    session.pop("is_commissioner", None)
    return redirect(url_for("home"))


def _extract_list(raw, wrapper_key, item_keys):
    """
    Flexibly pull a list of dicts out of a pasted ChatGPT response.

    Handles:
    - {"articles": [...]}  /  {"influences": [...]}   (wrapper object)
    - [{"headline": ...}, ...]                         (plain array)
    - {"headline": ...}                                (single item)
    - ```json ... ```  code fences (one or many blocks)
    - Free text with JSON embedded — finds the first { or [ and parses from there
    - Multiple code blocks, each containing one item or a list
    """
    import re as _re

    if not raw:
        return []

    # Pull out every ```json ... ``` or ``` ... ``` block.
    # If none found, treat the whole paste as one candidate.
    code_blocks = _re.findall(r"```(?:json)?\s*([\s\S]*?)```", raw)
    candidates = code_blocks if code_blocks else [raw]

    results = []
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue

        # Find the first JSON delimiter ({ or [), whichever comes first.
        ci = candidate.find("{")
        bi = candidate.find("[")
        if ci < 0 and bi < 0:
            continue
        if bi >= 0 and (ci < 0 or bi < ci):
            start = bi
        else:
            start = ci

        try:
            data = json.loads(candidate[start:])
        except json.JSONDecodeError:
            continue

        if isinstance(data, list):
            results.extend(data)
        elif isinstance(data, dict):
            if wrapper_key in data and isinstance(data[wrapper_key], list):
                results.extend(data[wrapper_key])
            elif any(k in data for k in item_keys):
                # Single item — wrap it
                results.append(data)

    return results


def capture_output(callback):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        callback()
    return buffer.getvalue().strip()


def with_conn(callback):
    create_tables()
    conn = get_connection()
    try:
        return callback(conn)
    finally:
        conn.close()


def render_no_league():
    return render_template("no_league.html")


@app.template_filter("money")
def money(value):
    if value is None:
        return "-"
    return f"${value / 1_000_000:.1f}M"


@app.template_filter("diff")
def diff(value):
    if value is None:
        return "-"
    return f"+{value}" if value > 0 else str(value)


@app.template_filter("pct")
def pct(value):
    if value is None:
        return ".000"
    return f"{value:.3f}".lstrip("0")


@app.template_filter("event_label")
def event_label(value):
    return (value or "").replace("_", " ").title()


@app.context_processor
def inject_chrome():
    def load():
        return with_conn(q.get_site_chrome)

    try:
        chrome = load()
    except Exception:
        chrome = {"state": None, "teams": []}
    return chrome


@app.route("/")
def home():
    def load(conn):
        return {"state": q.get_state(conn)}
    try:
        data = with_conn(load)
    except Exception:
        data = {"state": None}
    return render_template("landing.html", **(data or {"state": None}), active="home")


@app.route("/live-league")
def live_league():
    followed_team_id = _followed_team_id()

    def load(conn):
        state = q.get_state(conn)
        if not state:
            return None
        season = state["season_year"]
        phase = state.get("phase", "regular_season")
        bracket = get_bracket(conn, season) if phase in ("playoffs", "complete") else []
        playoff = get_playoff_snapshot(conn, season) if phase in ("playoffs", "complete") else None
        latest_results = q.latest_results(conn, season, limit=6)
        forms = q.team_form(conn, season)
        articles = q.recent_articles(conn, season, limit=5)
        top_story = articles[0] if articles else None
        if not top_story and latest_results:
            explanation = conn.execute(
                "SELECT factual_recap, standings_impact FROM game_explanations WHERE game_id=?",
                (latest_results[0]["id"],),
            ).fetchone()
            if explanation:
                top_story = {
                    "headline": explanation["standings_impact"] or "The latest week changed the league",
                    "body": explanation["factual_recap"],
                    "week": latest_results[0]["week"],
                    "story_role": "lead",
                }
        offseason_events = q.offseason_events(conn, limit=len(OFFSEASON_STAGES)) if phase == "offseason" else []
        offseason_stage = state.get("offseason_stage") or "retirements"
        completed_offseason_stages = {event["stage"] for event in offseason_events}
        offseason_stages = [
            {
                "key": stage_key,
                "label": OFFSEASON_STAGE_LABELS.get(stage_key, stage_key.replace("_", " ").title()),
                "status": (
                    "current" if stage_key == offseason_stage
                    else "complete" if stage_key in completed_offseason_stages
                    else "upcoming"
                ),
            }
            for stage_key in OFFSEASON_STAGES
        ]
        return {
            "state": state,
            "phase": phase,
            "bracket": bracket,
            "playoff": playoff,
            "offseason_stage_label": OFFSEASON_STAGE_LABELS.get(
                offseason_stage,
                offseason_stage.replace("_", " ").title(),
            ),
            "offseason_stages": offseason_stages,
            "offseason_events": offseason_events,
            "games_played": q.get_games_played(conn, season),
            "max_week": q.get_max_week(conn, season),
            "standings": q.standings(conn, season, limit=6),
            "leaders": q.stat_leaders(conn, season, limit=6),
            "mvp_ladder": q.mvp_ladder(conn, season, limit=5),
            "latest_results": latest_results,
            "latest_articles": articles[:3],
            "top_story": top_story,
            "next_featured_game": q.next_featured_game(
                conn, season, state["current_week"]
            ),
            "hot_team": forms[0] if forms else None,
            "cold_team": forms[-1] if forms else None,
            "trade_pressure": q.trade_pressure(conn, season),
            "fan_poll": q.active_poll(conn, season),
            "followed_team": q.followed_team_feed(
                conn, followed_team_id, season
            ),
            "storylines": q.public_storylines(conn, season, limit=6),
        }

    data = with_conn(load)
    if not data:
        return render_no_league()
    return render_template("home.html", **data, active="live_league")


@app.route("/standings")
def standings():
    def load(conn):
        state = q.get_state(conn)
        if not state:
            return None
        return {
            "state": state,
            "standings": q.standings(conn, state["season_year"]),
        }

    data = with_conn(load)
    if not data:
        return render_no_league()
    return render_template("standings.html", **data, active="standings")


@app.route("/teams")
def teams():
    followed_team_id = _followed_team_id()

    def load(conn):
        state = q.get_state(conn)
        if not state:
            return None
        return {
            "state": state,
            "team_rows": q.teams_index(conn, state["season_year"]),
            "followed_team_id": followed_team_id,
        }

    data = with_conn(load)
    if not data:
        return render_no_league()
    return render_template("teams.html", **data, active="teams")


@app.route("/teams/<abbr>")
def team_page(abbr):
    followed_team_id = _followed_team_id()

    def load(conn):
        state = q.get_state(conn)
        if not state:
            return None
        detail = q.team_detail(conn, abbr, state["season_year"])
        return {
            "state": state,
            "detail": detail,
            "is_followed": bool(detail and detail["team"]["id"] == followed_team_id),
        }

    data = with_conn(load)
    if not data:
        return render_no_league()
    if not data["detail"]:
        return render_template("not_found.html", title="Team not found"), 404
    return render_template("team_detail.html", **data, active="teams")


@app.route("/players")
def players():
    team_id = request.args.get("team_id", type=int)

    def load(conn):
        state = q.get_state(conn)
        if not state:
            return None
        return {
            "state": state,
            "selected_team_id": team_id,
            "player_rows": q.players_index(conn, team_id=team_id),
        }

    data = with_conn(load)
    if not data:
        return render_no_league()
    return render_template("players.html", **data, active="players")


@app.route("/players/<int:player_id>")
def player_page(player_id):
    def load(conn):
        state = q.get_state(conn)
        if not state:
            return None
        detail = q.player_detail(conn, player_id, state["season_year"])
        return {"state": state, "detail": detail}

    data = with_conn(load)
    if not data:
        return render_no_league()
    if not data["detail"]:
        return render_template("not_found.html", title="Player not found"), 404
    return render_template("player_detail.html", **data, active="players")


@app.route("/scores")
@app.route("/scores/week/<int:week>")
def scores(week=None):
    def load(conn):
        state = q.get_state(conn)
        if not state:
            return None
        selected_week, games = q.games_for_week(conn, state["season_year"], week=week)
        return {
            "state": state,
            "selected_week": selected_week,
            "played_weeks": q.get_played_weeks(conn, state["season_year"]),
            "games": games,
        }

    data = with_conn(load)
    if not data:
        return render_no_league()
    return render_template("scores.html", **data, active="scores")


@app.route("/games/<int:game_id>")
def game_page(game_id):
    def load(conn):
        detail = q.game_detail(conn, game_id)
        state = q.get_state(conn)
        return {"state": state, "detail": detail}

    data = with_conn(load)
    if not data["state"]:
        return render_no_league()
    if not data["detail"]:
        return render_template("not_found.html", title="Game not found"), 404
    return render_template("game_detail.html", **data, active="scores")


@app.route("/leaders")
def leaders():
    def load(conn):
        state = q.get_state(conn)
        if not state:
            return None
        season = state["season_year"]
        return {
            "state": state,
            "ppg": q.stat_leaders(conn, season, limit=12, order_by="ppg"),
            "rpg": q.stat_leaders(conn, season, limit=12, order_by="rpg"),
            "apg": q.stat_leaders(conn, season, limit=12, order_by="apg"),
            "spg": q.stat_leaders(conn, season, limit=12, order_by="spg"),
            "bpg": q.stat_leaders(conn, season, limit=12, order_by="bpg"),
        }

    data = with_conn(load)
    if not data:
        return render_no_league()
    return render_template("leaders.html", **data, active="leaders")


@app.route("/news")
def news():
    def load(conn):
        state = q.get_state(conn)
        if not state:
            return None
        season = state["season_year"]
        return {
            "state": state,
            "articles": q.recent_articles(conn, season, limit=40),
            "storylines": q.public_storylines(conn, season, limit=40),
            "interviews": get_recent_interviews(conn, season, limit=20),
            "editorial_quotes": q.recent_editorial_quotes(conn, season, limit=20),
        }

    data = with_conn(load)
    if not data:
        return render_no_league()
    return render_template("news.html", **data, active="news")


@app.post("/follow-team")
def follow_team():
    team_id = request.form.get("team_id", type=int)
    destination = request.form.get("next") or url_for("live_league")

    def valid(conn):
        return q.team_by_id(conn, team_id)

    team = with_conn(valid)
    if not team:
        flash("That team could not be followed.", "error")
        return redirect(destination)
    response = redirect(destination)
    response.set_cookie(
        "aiba_followed_team",
        _cookie_serializer().dumps(str(team_id)),
        max_age=60 * 60 * 24 * 365 * 3,
        httponly=True,
        samesite="Lax",
    )
    flash(f"You now follow the {team['team_name']}.", "success")
    return response


@app.post("/unfollow-team")
def unfollow_team():
    destination = request.form.get("next") or url_for("teams")
    response = redirect(destination)
    response.delete_cookie("aiba_followed_team")
    flash("Your team follow has been cleared.", "success")
    return response


@app.post("/polls/<int:poll_id>/vote")
def poll_vote(poll_id):
    option_id = request.form.get("option_id", type=int)
    destination = request.form.get("next") or url_for("live_league")
    token, voter_hash = _fan_voter_hash()
    try:
        def save(conn):
            cast_poll_vote(conn, poll_id, option_id, voter_hash)
        with_conn(save)
        flash("Vote counted. The league remains autonomous; this is the fan verdict.", "success")
    except Exception as exc:
        flash(str(exc), "error")
    response = redirect(destination)
    if not request.cookies.get("aiba_fan_token"):
        response.set_cookie(
            "aiba_fan_token",
            _cookie_serializer().dumps(token),
            max_age=60 * 60 * 24 * 365 * 3,
            httponly=True,
            samesite="Lax",
        )
    return response


@app.route("/history")
def history():
    def load(conn):
        state = q.get_state(conn)
        if not state:
            return None
        return {"state": state, **q.history_overview(conn)}

    data = with_conn(load)
    if not data:
        return render_no_league()
    return render_template("history.html", **data, active="history")


def commissioner_data():
    def load(conn):
        state = q.get_state(conn)
        if not state:
            return None
        season = state["season_year"]
        return {
            "state": state,
            "games_played": q.get_games_played(conn, season),
            "max_week": q.get_max_week(conn, season),
            "pending_trades": q.pending_trades(conn),
            "logs": q.commissioner_logs(conn),
            "offseason_events": q.offseason_events(conn),
            "team_options": q.teams_index(conn, season),
            "trade_options": q.trade_options(conn),
            "editorial_package": q.current_editorial_package(conn, season),
            "recent_interviews": get_recent_interviews(conn, season, limit=20),
            "fan_poll": q.active_poll(conn, season),
        }

    data = with_conn(load)
    if not data:
        return None

    state = data["state"]
    season = state["season_year"]
    week = state["current_week"]
    phase = state.get("phase", "regular_season")
    offseason_stage = state.get("offseason_stage") or "retirements"
    data["offseason_stage_label"] = OFFSEASON_STAGE_LABELS.get(
        offseason_stage,
        offseason_stage.replace("_", " ").title(),
    )
    return data

    def try_packet(context_type, prompt, **kwargs):
        try:
            return build_chatgpt_packet(context_type, prompt, **kwargs)
        except Exception:
            return None

    data["auto_snapshot"] = try_packet(
        "League snapshot",
        f"Season {season}, Week {week}: Summarize the league — standings story, "
        f"top performers, biggest upsets or surprises, and which storylines are "
        f"heating up right now."
    )
    data["auto_power_rankings"] = try_packet(
        "League snapshot",
        f"Season {season}, Week {week}: Rank all teams from 1 (strongest) to last "
        f"(weakest). For each team write one sentence covering their record, best "
        f"player, and current outlook. Bold the #1 team."
    )
    data["auto_week_preview"] = try_packet(
        "League snapshot",
        f"Season {season}: Preview Week {week + 1}. Which matchups matter most for "
        f"the standings? Which players are must-watches? What storylines could shift "
        f"in the coming week?"
    )
    data["auto_playoff_packets"] = []
    if phase in ("playoffs", "complete"):
        playoff_requests = [
            (
                "Playoff Week Recap",
                f"Season {season}, Playoff Week {week}: Write a postseason recap from the live bracket data. "
                "Focus on series scores, clinches, pressure, standout players, and what changed in the bracket."
            ),
            (
                "Series Preview",
                f"Season {season}: Preview the next scheduled playoff games. Explain the stakes for every active "
                "Finals, third-place, or semifinal series and identify must-watch players."
            ),
            (
                "Elimination Storylines",
                f"Season {season}: Find the biggest elimination-game or clinching-game storylines in the playoff "
                "bracket. Create news hooks and suggested influences based only on the included data."
            ),
        ]
        for label, prompt in playoff_requests:
            pkt = try_packet("League snapshot", prompt)
            if pkt:
                data["auto_playoff_packets"].append({
                    "label": label,
                    "packet": pkt,
                })

    auto_team_packets = []
    for team in data["team_options"]:
        pkt = try_packet(
            "Team report",
            f"Write a narrative team report on the {team['team_name']}: recent game "
            f"results, standout and struggling players, GM personality and trade "
            f"tendencies, and what the commissioner should keep an eye on.",
            team_id=team["id"]
        )
        if pkt:
            auto_team_packets.append({
                "id": team["id"],
                "team_name": team["team_name"],
                "abbreviation": team["abbreviation"],
                "packet": pkt,
            })
    data["auto_team_packets"] = auto_team_packets

    auto_trade_packets = []
    for trade in data["pending_trades"]:
        pkt = try_packet(
            "Pending trade review",
            f"Analyze this proposed trade between {trade['proposing_team']} and "
            f"{trade['receiving_team']}. Is it fair? Who benefits more? What is each "
            f"GM's likely motivation? Should the commissioner approve, push back, or "
            f"veto it? Give a clear recommendation.",
            trade_id=trade["id"]
        )
        if pkt:
            auto_trade_packets.append({
                "trade_id": trade["id"],
                "proposing_team": trade["proposing_team"],
                "receiving_team": trade["receiving_team"],
                "packet": pkt,
            })
    data["auto_trade_packets"] = auto_trade_packets

    return data


@app.route("/about")
def about():
    def load(conn):
        return {"state": q.get_state(conn)}
    data = with_conn(load)
    return render_template("about.html", **(data or {"state": None}), active="about")


@app.route("/contact")
def contact():
    def load(conn):
        return {"state": q.get_state(conn)}
    data = with_conn(load)
    return render_template("contact.html", **(data or {"state": None}), active="contact")


@app.route("/terms")
def terms():
    def load(conn):
        return {"state": q.get_state(conn)}
    data = with_conn(load)
    return render_template("terms.html", **(data or {"state": None}), active="terms")


@app.route("/privacy")
def privacy():
    def load(conn):
        return {"state": q.get_state(conn)}
    data = with_conn(load)
    return render_template("privacy.html", **(data or {"state": None}), active="privacy")


@app.route("/sitemap.xml")
def sitemap():
    base_url = request.url_root.rstrip("/")
    xml = render_template("sitemap.xml", base_url=base_url)
    return Response(xml, mimetype="application/xml")


@app.route("/robots.txt")
def robots():
    base_url = request.url_root.rstrip("/")
    content = f"User-agent: *\nAllow: /\nSitemap: {base_url}/sitemap.xml\n"
    return Response(content, mimetype="text/plain")


@app.route("/commissioner")
@require_commissioner
def commissioner():
    data = commissioner_data()
    if not data:
        return render_no_league()
    return render_template("commissioner.html", **data, active="commissioner")


@app.post("/commissioner/action")
@require_commissioner
def commissioner_action():
    action = request.form.get("action")

    try:
        if action == "run_week":
            output = capture_output(lambda: run_week(verbose=False, start_official=False))
            flash(output or "Week action completed.", "operation")
        elif action == "start_official":
            output = capture_output(lambda: run_week(verbose=False, start_official=True))
            flash(output or "Official Week 1 action completed.", "operation")
        elif action == "run_offseason":
            output = capture_output(lambda: advance_offseason_from_default_db(verbose=True))
            flash(output or "Offseason completed.", "operation")
        elif action == "run_full_offseason":
            output = capture_output(
                lambda: advance_full_offseason_from_default_db(verbose=True)
            )
            flash(output or "The full offseason completed.", "operation")
        elif action == "approve_trade":
            trade_id = request.form.get("trade_id", type=int)
            output = approve_trade(trade_id)
            flash(output, "operation")
        elif action == "veto_trade":
            trade_id = request.form.get("trade_id", type=int)
            reason = request.form.get("reason", "").strip() or "Vetoed by commissioner."
            output = veto_trade_action(trade_id, reason)
            flash(output, "operation")
        elif action == "skip_trade":
            trade_id = request.form.get("trade_id", type=int)
            flash(f"Trade #{trade_id} skipped. It remains pending.", "operation")
        else:
            flash("Unknown commissioner action.", "error")
    except Exception as exc:
        flash(str(exc), "error")

    return redirect(url_for("commissioner"))


def approve_trade(trade_id):
    if not trade_id:
        return "No trade selected."
    create_tables()
    conn = get_connection()
    try:
        ok, reason = validate_trade(conn, trade_id)
        if not ok:
            invalidate_trade(conn, trade_id, reason)
            return f"Trade #{trade_id} failed validation and was marked invalid: {reason}"
        execute_trade(conn, trade_id)
        return f"Trade #{trade_id} approved and executed."
    finally:
        conn.close()


def veto_trade_action(trade_id, reason):
    if not trade_id:
        return "No trade selected."
    create_tables()
    conn = get_connection()
    try:
        veto_trade(conn, trade_id, reason)
        return f"Trade #{trade_id} vetoed: {reason}"
    finally:
        conn.close()


@app.post("/commissioner/editorial/publish")
@require_commissioner
def commissioner_editorial_publish():
    raw = (request.form.get("editorial_json") or "").strip()
    if not raw:
        flash("Paste the weekly ChatGPT response first.", "error")
        return redirect(url_for("commissioner") + "#editorial")
    try:
        def publish(conn):
            return publish_weekly_editorial(conn, raw)
        articles, quotes, duplicate = with_conn(publish)
        if duplicate:
            flash("That exact weekly package was already published.", "success")
        else:
            flash(
                f"Published {articles} stories and {quotes} character quotes.",
                "success",
            )
    except Exception as exc:
        flash(str(exc), "error")
    return redirect(url_for("commissioner") + "#editorial")


@app.post("/commissioner/articles/add")
@require_commissioner
def commissioner_articles_add():
    raw = request.form.get("articles_json", "").strip()
    if not raw:
        flash("No JSON provided.", "error")
        return redirect(url_for("commissioner"))

    article_list = _extract_list(raw, "articles", ["headline", "body"])
    if not article_list:
        flash("No articles found. Paste a JSON array, a {\"articles\":[...]} object, or a response containing ```json``` blocks.", "error")
        return redirect(url_for("commissioner"))

    def save(conn):
        state = q.get_state(conn)
        current_week = state["current_week"] if state else 1
        season_year = state["season_year"] if state else 2026
        count = 0
        for art in article_list:
            headline = (art.get("headline") or "").strip()
            body = (art.get("body") or "").strip()
            if not headline or not body:
                continue
            week = int(art.get("week") or current_week)
            cur = conn.execute(
                "INSERT INTO articles (week, season_year, headline, body) VALUES (?, ?, ?, ?)"
                " RETURNING id",
                (week, season_year, headline, body),
            )
            article_id = cur.fetchone()["id"]
            for abbr in art.get("team_tags") or []:
                row = conn.execute(
                    "SELECT id FROM teams WHERE UPPER(abbreviation) = UPPER(?)", (abbr,)
                ).fetchone()
                if row:
                    conn.execute(
                        "INSERT INTO article_tags (article_id, tag_type, tag_id) VALUES (?, 'team', ?)",
                        (article_id, row["id"]),
                    )
            for name in art.get("player_tags") or []:
                parts = name.strip().split(None, 1)
                if len(parts) == 2:
                    row = conn.execute(
                        "SELECT id FROM players WHERE LOWER(first_name)=LOWER(?) AND LOWER(last_name)=LOWER(?)",
                        (parts[0], parts[1]),
                    ).fetchone()
                    if row:
                        conn.execute(
                            "INSERT INTO article_tags (article_id, tag_type, tag_id) VALUES (?, 'player', ?)",
                            (article_id, row["id"]),
                        )
            count += 1
        conn.commit()
        return count

    count = with_conn(save)
    flash(f"{count} article{'s' if count != 1 else ''} published to the league.", "operation")
    return redirect(url_for("commissioner"))


@app.post("/commissioner/influences/add")
@require_commissioner
def commissioner_influences_add():
    raw = request.form.get("influences_json", "").strip()
    if not raw:
        flash("No JSON provided.", "error")
        return redirect(url_for("commissioner"))
    influence_list = _extract_list(raw, "influences", ["player", "team", "gm"])
    if not influence_list:
        flash("No influences found. Paste a JSON array, a {\"influences\":[...]} object, or a response containing ```json``` blocks.", "error")
        return redirect(url_for("commissioner"))

    def save(conn):
        state = q.get_state(conn)
        current_week = state["current_week"] if state else 1
        season_year = state["season_year"] if state else 2026
        count = 0

        for inf in influence_list:
            duration = max(1, int(inf.get("duration_weeks") or 2))
            expires = current_week + duration
            reason = (inf.get("reason") or "").strip() or None

            # ── Player influences ─────────────────────────────────────────────
            if inf.get("player"):
                parts = inf["player"].strip().split(None, 1)
                if len(parts) != 2:
                    continue
                row = conn.execute(
                    "SELECT id FROM players WHERE LOWER(first_name)=LOWER(?) AND LOWER(last_name)=LOWER(?)",
                    (parts[0], parts[1]),
                ).fetchone()
                if not row:
                    continue
                pid = row["id"]

                streak = (inf.get("streak") or "").lower()
                if streak == "hot":
                    mag = float(inf.get("magnitude") or 5.0)
                    conn.execute(
                        "INSERT INTO player_modifiers (player_id, week_set, season_year, expires_week, mod_type, magnitude, reason)"
                        " VALUES (?, ?, ?, ?, 'hot_streak', ?, ?)",
                        (pid, current_week, season_year, expires, mag, reason),
                    )
                elif streak == "cold":
                    mag = float(inf.get("magnitude") or 5.0)
                    conn.execute(
                        "INSERT INTO player_modifiers (player_id, week_set, season_year, expires_week, mod_type, magnitude, reason)"
                        " VALUES (?, ?, ?, ?, 'cold_streak', ?, ?)",
                        (pid, current_week, season_year, expires, mag, reason),
                    )

                morale_val = inf.get("morale")
                if morale_val is not None:
                    m = float(morale_val)
                    if m > 0:
                        conn.execute(
                            "INSERT INTO player_modifiers (player_id, week_set, season_year, expires_week, mod_type, magnitude, reason)"
                            " VALUES (?, ?, ?, ?, 'morale_boost', ?, ?)",
                            (pid, current_week, season_year, expires, abs(m), reason),
                        )
                    elif m < 0:
                        conn.execute(
                            "INSERT INTO player_modifiers (player_id, week_set, season_year, expires_week, mod_type, magnitude, reason)"
                            " VALUES (?, ?, ?, ?, 'morale_penalty', ?, ?)",
                            (pid, current_week, season_year, expires, abs(m), reason),
                        )

                we_boost = inf.get("work_ethic_boost")
                if we_boost:
                    conn.execute(
                        "INSERT INTO player_modifiers (player_id, week_set, season_year, expires_week, mod_type, magnitude, reason)"
                        " VALUES (?, ?, ?, ?, 'work_ethic_boost', ?, ?)",
                        (pid, current_week, season_year, expires, float(we_boost), reason),
                    )

                loyalty_drop = inf.get("loyalty_drop")
                if loyalty_drop:
                    conn.execute(
                        "INSERT INTO player_modifiers (player_id, week_set, season_year, expires_week, mod_type, magnitude, reason)"
                        " VALUES (?, ?, ?, ?, 'loyalty_drop', ?, ?)",
                        (pid, current_week, season_year, expires, float(loyalty_drop), reason),
                    )

                count += 1
                continue

            # ── Team influences ───────────────────────────────────────────────
            if inf.get("team"):
                team_row = conn.execute(
                    "SELECT id FROM teams WHERE UPPER(abbreviation) = UPPER(?)", (inf["team"],)
                ).fetchone()
                if not team_row:
                    continue
                tid = team_row["id"]

                momentum = (inf.get("momentum") or "").lower()
                if momentum == "hot":
                    mag = float(inf.get("magnitude") or 6.0)
                    conn.execute(
                        "INSERT INTO team_modifiers (team_id, week_set, season_year, expires_week, mod_type, magnitude, reason)"
                        " VALUES (?, ?, ?, ?, 'momentum_hot', ?, ?)",
                        (tid, current_week, season_year, expires, mag, reason),
                    )
                elif momentum == "cold":
                    mag = float(inf.get("magnitude") or 6.0)
                    conn.execute(
                        "INSERT INTO team_modifiers (team_id, week_set, season_year, expires_week, mod_type, magnitude, reason)"
                        " VALUES (?, ?, ?, ?, 'momentum_cold', ?, ?)",
                        (tid, current_week, season_year, expires, mag, reason),
                    )

                lr_boost = inf.get("locker_room_boost")
                if lr_boost:
                    conn.execute(
                        "INSERT INTO team_modifiers (team_id, week_set, season_year, expires_week, mod_type, magnitude, reason)"
                        " VALUES (?, ?, ?, ?, 'locker_room_boost', ?, ?)",
                        (tid, current_week, season_year, expires, float(lr_boost), reason),
                    )

                lr_penalty = inf.get("locker_room_penalty")
                if lr_penalty:
                    conn.execute(
                        "INSERT INTO team_modifiers (team_id, week_set, season_year, expires_week, mod_type, magnitude, reason)"
                        " VALUES (?, ?, ?, ?, 'locker_room_penalty', ?, ?)",
                        (tid, current_week, season_year, expires, float(lr_penalty), reason),
                    )

                count += 1
                continue

            # ── GM influences ─────────────────────────────────────────────────
            if inf.get("gm"):
                gm_row = conn.execute(
                    "SELECT gm.id FROM general_managers gm "
                    "JOIN teams t ON gm.team_id = t.id "
                    "WHERE UPPER(t.abbreviation) = UPPER(?)", (inf["gm"],)
                ).fetchone()
                if not gm_row:
                    continue
                gm_id = gm_row["id"]

                urgency = (inf.get("trade_urgency") or "").lower()
                if urgency == "high":
                    conn.execute(
                        "INSERT INTO gm_modifiers (gm_id, week_set, season_year, expires_week, mod_type, magnitude, reason)"
                        " VALUES (?, ?, ?, ?, 'trade_hungry', 0.15, ?)",
                        (gm_id, current_week, season_year, expires, reason),
                    )
                    count += 1
                elif urgency == "low":
                    conn.execute(
                        "INSERT INTO gm_modifiers (gm_id, week_set, season_year, expires_week, mod_type, magnitude, reason)"
                        " VALUES (?, ?, ?, ?, 'trade_conservative', 0.15, ?)",
                        (gm_id, current_week, season_year, expires, reason),
                    )
                    count += 1

        conn.commit()
        return count

    count = with_conn(save)
    flash(f"{count} influence{'s' if count != 1 else ''} applied to the league.", "operation")
    return redirect(url_for("commissioner"))


@app.route("/interviews")
def interviews():
    return redirect(url_for("commissioner") + "#interviews")


@app.route("/commissioner/interview/<int:interview_id>/submit", methods=["POST"])
@require_commissioner
def interview_submit(interview_id):
    response_text = (request.form.get("response") or "").strip()
    if not response_text:
        flash("No response text provided.", "error")
        return redirect(url_for("commissioner") + "#interviews")

    def save(conn):
        save_interview_response(interview_id, response_text, db=conn)

    with_conn(save)
    flash("Interview response saved and published!", "success")
    return redirect(url_for("commissioner") + "#interviews")


if __name__ == "__main__":
    debug = os.environ.get("AIBA_DEBUG") == "1"
    app.run(debug=debug, use_reloader=debug)
