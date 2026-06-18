"""
Seed player backstories for all existing players.
Safe to run multiple times — uses INSERT OR REPLACE so it won't duplicate.

Usage:
    python seed_backstories.py
"""
import random
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from league.database import get_connection, create_tables

# Basketball-heavy states get higher weight
COLLEGE_STATES = [
    ("Kentucky", 8), ("North Carolina", 8), ("Kansas", 7), ("Indiana", 7),
    ("Texas", 7), ("Florida", 6), ("California", 6), ("Ohio", 5),
    ("Tennessee", 5), ("Michigan", 5), ("Georgia", 4), ("Illinois", 4),
    ("Virginia", 4), ("Arizona", 4), ("Connecticut", 4), ("Louisiana", 3),
    ("Maryland", 3), ("Alabama", 3), ("Pennsylvania", 3), ("New York", 3),
    ("Oregon", 2), ("Utah", 2), ("Nevada", 2), ("Wisconsin", 2),
    ("Minnesota", 2), ("Arkansas", 2), ("South Carolina", 2),
    ("Mississippi", 2), ("Iowa", 2), ("Colorado", 2),
    ("Oklahoma", 2), ("Missouri", 2), ("West Virginia", 2),
    ("International", 5),
]

HOMETOWN_STATES = [
    "Alabama", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Florida", "Georgia", "Illinois", "Indiana",
    "Iowa", "Kansas", "Kentucky", "Louisiana", "Maryland",
    "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri",
    "Nevada", "New Jersey", "New York", "North Carolina", "Ohio",
    "Oklahoma", "Oregon", "Pennsylvania", "South Carolina", "Tennessee",
    "Texas", "Utah", "Virginia", "Washington", "Wisconsin",
]

ARCHETYPE_TO_LABEL = {
    "hothead":             "Fiery Competitor",
    "superstar_ego":       "The Showman",
    "malcontent":          "Disgruntled Vet",
    "quiet_professional":  "Cool Under Pressure",
    "locker_room_leader":  "The Glue Guy",
    "rising_star":         "Hungry Underdog",
    "aging_veteran":       "The Wise One",
    "team_player":         "Low-Maintenance Pro",
}

# Templates: (archetype, result_type) -> list of blurb templates
# {hometown}, {college} are filled in at runtime
BLURB_TEMPLATES = {
    "hothead": [
        "Raised in {hometown} with fire in his eyes, {first} played college ball in {college} and never learned to stay calm under pressure — and he wouldn't have it any other way.",
        "A product of {hometown} AAU circuits, {first} brought his signature intensity from the courts of {college} straight to the pro game.",
        "{first} grew up in {hometown} and earned a reputation in {college} for being the kind of player coaches loved and opponents hated.",
    ],
    "superstar_ego": [
        "From {hometown} to the spotlight — {first} made headlines at every level, turning heads in {college} before demanding the same attention as a pro.",
        "{first} was the best player on every team he touched growing up in {hometown}, and two years in {college} only made him believe it more.",
        "Built for big moments, {first} came out of {hometown} and became the face of his program in {college} before anyone outside the league knew his name.",
    ],
    "malcontent": [
        "{first} came up the hard way in {hometown} and never forgot it. He put in the work at {college}, but somewhere along the line the league stopped feeling like it owed him anything.",
        "A former standout from {college}, {first} grew up in {hometown} where he learned to expect more — from coaches, from teammates, from front offices.",
        "They said {first} had all the tools coming out of {college}. Grew up in {hometown} with a chip that never quite wore off.",
    ],
    "quiet_professional": [
        "Nobody in {hometown} thought {first} would make it. He went to {college} and let his game do the talking — and it's been talking ever since.",
        "{first} doesn't do interviews, doesn't seek attention. He came out of {college} after growing up quietly in {hometown}, and he's been the same ever since.",
        "Raised in {hometown} to keep his head down and work, {first} was the kind of player {college} coaches built their systems around without making a fuss.",
    ],
    "locker_room_leader": [
        "{first} was captain of his high school team in {hometown} and did the same at {college}. Leading comes naturally — he's just built that way.",
        "Everyone who's played with {first} says the same thing: he makes everyone better. He learned that in {college}, having grown up with a team-first mentality in {hometown}.",
        "From {hometown} youth leagues to {college} locker rooms, {first} was always the one teammates leaned on when things got hard.",
    ],
    "rising_star": [
        "{first} wasn't heavily recruited out of {hometown}, walked on at {college}, and worked his way into a starting role no one predicted. He hasn't stopped climbing since.",
        "Overlooked in {hometown}, underestimated at {college} — {first} uses every slight as fuel. Give him a reason to prove you wrong and he will.",
        "One year at {college} was all {first} needed after growing up scrapping for every minute of court time in {hometown}. He came into the pro game with something to prove.",
    ],
    "aging_veteran": [
        "{first} has seen enough basketball in {college} and beyond to write a book. He grew up in {hometown}, made it to the pros, and is still here because nobody works harder.",
        "At this point in his career, {first} just wants to win. He remembers what it cost to get here from {hometown} through {college}, and he's not done yet.",
        "{first} grew up in {hometown}, made a name in {college}, and has played through more injuries and roster moves than most players survive. He'll retire on his own terms.",
    ],
    "team_player": [
        "{first} grew up in {hometown} without an ego, played the right way at {college}, and brought that same attitude to the pros. He just wants to play and win.",
        "Ask {first} about scoring titles or all-star nods and he'll shrug. He came out of {college} after growing up in {hometown} as the kind of player who makes teams better — quietly.",
        "No drama, no demands. {first} learned to play the right way in {hometown}, refined it at {college}, and never saw a reason to change.",
    ],
}


def _pick_college_state():
    population = [state for state, weight in COLLEGE_STATES for _ in range(weight)]
    return random.choice(population)


def _pick_hometown(college_state):
    options = [s for s in HOMETOWN_STATES if s != college_state]
    # 20% chance hometown == college state
    if random.random() < 0.20 and college_state in HOMETOWN_STATES:
        return college_state
    return random.choice(options)


def _build_blurb(archetype, first_name, hometown, college):
    templates = BLURB_TEMPLATES.get(archetype, BLURB_TEMPLATES["team_player"])
    template = random.choice(templates)
    college_str = college if college != "International" else "overseas"
    return template.format(first=first_name, hometown=hometown, college=college_str)


def seed_backstories():
    create_tables()
    conn = get_connection()

    players = conn.execute("""
        SELECT p.id, p.first_name, pp.archetype
        FROM players p
        LEFT JOIN player_personalities pp ON pp.player_id = p.id
        WHERE COALESCE(p.status, 'active') = 'active'
    """).fetchall()

    count = 0
    for row in players:
        player_id = row["id"]
        first_name = row["first_name"]
        archetype = row["archetype"] or "team_player"
        personality_label = ARCHETYPE_TO_LABEL.get(archetype, "Low-Maintenance Pro")
        college_state = _pick_college_state()
        hometown_state = _pick_hometown(college_state)
        blurb = _build_blurb(archetype, first_name, hometown_state, college_state)

        conn.execute("""
            INSERT INTO player_backstories
                (player_id, college_state, hometown_state, personality_label, backstory_blurb)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (player_id) DO UPDATE SET
                college_state = EXCLUDED.college_state,
                hometown_state = EXCLUDED.hometown_state,
                personality_label = EXCLUDED.personality_label,
                backstory_blurb = EXCLUDED.backstory_blurb
        """, (player_id, college_state, hometown_state, personality_label, blurb))
        count += 1

    conn.commit()
    conn.close()
    print(f"{count} backstories seeded.")


if __name__ == "__main__":
    seed_backstories()
