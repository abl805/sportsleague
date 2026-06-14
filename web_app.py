import contextlib
import io
import os

from flask import Flask, flash, redirect, render_template, request, url_for

from league import web_queries as q
from league.chatgpt_bridge import (
    build_chatgpt_packet,
    parse_chatgpt_response,
    response_template,
)
from league.database import create_tables, get_connection
from league.offseason import advance_offseason_from_default_db
from league.trade_engine import execute_trade, invalidate_trade, validate_trade, veto_trade
from run_week import run_week


app = Flask(__name__)
app.secret_key = os.environ.get("AIBL_SECRET_KEY", "aibl-local-dev-console")


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
        state = q.get_state(conn)
        if not state:
            return None
        season = state["season_year"]
        return {
            "state": state,
            "games_played": q.get_games_played(conn, season),
            "max_week": q.get_max_week(conn, season),
            "standings": q.standings(conn, season, limit=6),
            "leaders": q.stat_leaders(conn, season, limit=6),
            "latest_results": q.latest_results(conn, season, limit=6),
            "storylines": q.public_storylines(conn, season, limit=6),
        }

    data = with_conn(load)
    if not data:
        return render_no_league()
    return render_template("home.html", **data, active="home")


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
    def load(conn):
        state = q.get_state(conn)
        if not state:
            return None
        return {"state": state, "team_rows": q.teams_index(conn, state["season_year"])}

    data = with_conn(load)
    if not data:
        return render_no_league()
    return render_template("teams.html", **data, active="teams")


@app.route("/teams/<abbr>")
def team_page(abbr):
    def load(conn):
        state = q.get_state(conn)
        if not state:
            return None
        detail = q.team_detail(conn, abbr, state["season_year"])
        return {"state": state, "detail": detail}

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


@app.route("/storylines")
def storylines():
    def load(conn):
        state = q.get_state(conn)
        if not state:
            return None
        return {
            "state": state,
            "storylines": q.public_storylines(conn, state["season_year"], limit=40),
        }

    data = with_conn(load)
    if not data:
        return render_no_league()
    return render_template("storylines.html", **data, active="storylines")


def commissioner_data(packet=None, parsed_response=None, parse_warning=None, form=None):
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
            "team_options": q.teams_index(conn, season),
            "trade_options": q.trade_options(conn),
            "packet": packet,
            "parsed_response": parsed_response,
            "parse_warning": parse_warning,
            "packet_template": response_template((form or {}).get("context_type", "League snapshot")),
            "form": form or {},
        }

    return with_conn(load)


@app.route("/commissioner")
def commissioner():
    data = commissioner_data()
    if not data:
        return render_no_league()
    return render_template("commissioner.html", **data, active="commissioner")


@app.post("/commissioner/action")
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


@app.post("/commissioner/packet")
def commissioner_packet():
    context_type = request.form.get("context_type", "League snapshot")
    commissioner_request = request.form.get("commissioner_request", "").strip()
    team_id = request.form.get("team_id", type=int)
    trade_id = request.form.get("trade_id", type=int)
    pasted_response = request.form.get("pasted_response", "")
    form = {
        "context_type": context_type,
        "commissioner_request": commissioner_request,
        "team_id": team_id,
        "trade_id": trade_id,
        "pasted_response": pasted_response,
    }

    packet = None
    parsed_response = None
    parse_warning = None
    try:
        if request.form.get("build_packet"):
            packet = build_chatgpt_packet(
                context_type,
                commissioner_request,
                team_id=team_id,
                trade_id=trade_id,
            )
        if pasted_response.strip():
            parsed_response, parse_warning = parse_chatgpt_response(pasted_response)
    except Exception as exc:
        flash(str(exc), "error")

    data = commissioner_data(
        packet=packet,
        parsed_response=parsed_response,
        parse_warning=parse_warning,
        form=form,
    )
    if not data:
        return render_no_league()
    return render_template("commissioner.html", **data, active="commissioner")


if __name__ == "__main__":
    debug = os.environ.get("AIBL_DEBUG") == "1"
    app.run(debug=debug, use_reloader=debug)
