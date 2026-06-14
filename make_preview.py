import os
import re

from web_app import app


OUT_DIR = os.path.join(os.path.dirname(__file__), "preview_static")

ROUTES = {
    "/": "index.html",
    "/standings": "standings.html",
    "/teams": "teams.html",
    "/players": "players.html",
    "/scores": "scores.html",
    "/leaders": "leaders.html",
    "/storylines": "storylines.html",
    "/commissioner": "commissioner.html",
}


def rewrite_links(html):
    html = html.replace('href="/static/site.css"', 'href="../static/site.css"')
    for route, filename in sorted(ROUTES.items(), key=lambda item: len(item[0]), reverse=True):
        html = html.replace(f'href="{route}"', f'href="{filename}"')
    html = re.sub(r'href="/teams/([^"]+)"', r'href="teams.html"', html)
    html = re.sub(r'href="/players/([^"]+)"', r'href="players.html"', html)
    html = re.sub(r'href="/games/([^"]+)"', r'href="scores.html"', html)
    html = re.sub(r'href="/scores/week/([^"]+)"', r'href="scores.html"', html)
    return html


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    with app.test_client() as client:
        for route, filename in ROUTES.items():
            response = client.get(route)
            if response.status_code != 200:
                raise RuntimeError(f"{route} returned {response.status_code}")
            html = rewrite_links(response.get_data(as_text=True))
            path = os.path.join(OUT_DIR, filename)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(html)
            print(f"Wrote {path}")


if __name__ == "__main__":
    main()
