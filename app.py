
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import re
from pathlib import Path

st.set_page_config(page_title="DraftKings Best Ball Optimizer", page_icon="🏈", layout="wide")

DATA = Path(__file__).with_name("22-25 Draft Data.xlsx")

# ============================================================
# SETTINGS
# ============================================================
TEAMS = 12
ROUNDS = 20

# Flexible roster-construction ranges for the optimizer.
# These are strategy targets, not DraftKings hard rules.
ROSTER_MIN = {"QB": 2, "RB": 4, "WR": 7, "TE": 2}
ROSTER_MAX = {"QB": 3, "RB": 7, "WR": 10, "TE": 3}

STYLE_WEIGHTS = {
    "Safe": {
        "early":  {"ppg": .40, "worth": .35, "boom": .10, "value": .15},
        "middle": {"ppg": .35, "worth": .30, "boom": .20, "value": .15},
        "late":   {"ppg": .25, "worth": .25, "boom": .35, "value": .15},
    },
    "Balanced": {
        "early":  {"ppg": .35, "worth": .30, "boom": .20, "value": .15},
        "middle": {"ppg": .30, "worth": .25, "boom": .30, "value": .15},
        "late":   {"ppg": .20, "worth": .20, "boom": .45, "value": .15},
    },
    "High Upside": {
        "early":  {"ppg": .30, "worth": .25, "boom": .30, "value": .15},
        "middle": {"ppg": .20, "worth": .20, "boom": .45, "value": .15},
        "late":   {"ppg": .10, "worth": .15, "boom": .60, "value": .15},
    }
}

FORCED_BUILDS = {
    "Open / Best Available": {},
    "RB-RB": {1: "RB", 2: "RB"},
    "WR-WR": {1: "WR", 2: "WR"},
    "RB-WR": {1: "RB", 2: "WR"},
    "WR-RB": {1: "WR", 2: "RB"},
    "Early TE": {1: "TE"},
    "Early QB": {1: "QB"},
    "Hero RB": {1: "RB", 2: "WR", 3: "WR"},
    "Zero RB": {1: "WR", 2: "WR", 3: "WR"},
}

# ============================================================
# LOAD DATA
# ============================================================
@st.cache_data
def load_data():
    hist = pd.read_excel(DATA, sheet_name="22-25")
    adp26 = pd.read_excel(DATA, sheet_name="2026 ADP")
    finish = pd.read_excel(DATA, sheet_name="Finish Points", header=1)
    market = pd.read_excel(DATA, sheet_name="Positions By round")

    hist.columns = [str(c).strip() for c in hist.columns]
    adp26.columns = [str(c).strip() for c in adp26.columns]
    finish.columns = [str(c).strip().replace("*", "") for c in finish.columns]

    # historical
    for c in ["Year","RK","ADP","GP","AVG","TTL","Round","Boom 10%","Boom 15%","Boom 20%","Boom 25%","Boom 30%"]:
        if c in hist.columns:
            hist[c] = pd.to_numeric(hist[c], errors="coerce")
    hist["Position"] = hist["Position"].astype(str).str.strip().str.upper()
    hist["Player"] = hist["Player"].astype(str).str.strip()

    # Normalize rookie flag from the workbook.
    hist["Is Rookie"] = (
        hist["Rookie?"].astype(str).str.strip().str.lower()
        .isin(["rookie", "(r)", "r", "yes", "y", "true", "1"])
    )

    # 2026
    adp26["Rank"] = pd.to_numeric(adp26["Rank"], errors="coerce")
    adp26["Player"] = adp26["Player"].astype(str).str.strip()
    adp26["POS"] = adp26["POS"].astype(str).str.strip().str.upper()
    adp26["Position"] = adp26["POS"].str.extract(r"([A-Z]+)")
    adp26["Pos Rank"] = pd.to_numeric(adp26["POS"].str.extract(r"(\d+)")[0], errors="coerce")
    adp26["Bye"] = pd.to_numeric(adp26["Bye"], errors="coerce")

    # finish benchmark
    finish["POS"] = finish["POS"].astype(str).str.strip().str.upper()
    tier_cols = ["Top 2","3-5","6-10","11-15","16-25","26-35","36-50","51-65","66-80"]
    for c in tier_cols:
        finish[c] = pd.to_numeric(finish[c], errors="coerce")

    market = market.dropna(axis=1, how="all")
    market.columns = [str(c).strip() for c in market.columns]
    market = market.rename(columns={"Qb":"QB","Rb":"RB","Wr":"WR","Te":"TE"})
    market["Round"] = pd.to_numeric(market["Round"], errors="coerce")
    market = market.dropna(subset=["Round"]).copy()
    market["Round"] = market["Round"].astype(int)
    for p in ["QB","RB","WR","TE"]:
        market[p] = pd.to_numeric(market[p], errors="coerce")

    return hist, adp26, finish, market

hist, adp26, finish, market = load_data()

# ============================================================
# REDZONE ANALYTICS DATA + HELPERS
# ============================================================
REDZONE_FILE = Path(__file__).with_name("NFL Project 2025.xlsx")
REDZONE_SCHEDULE_FILE = Path(__file__).with_name("2025_NFL_Schedules.xlsx")

# Full NFL team name to abbreviation
TEAM_ABBREVIATIONS = {
    "Arizona Cardinals": "ARI",
    "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR",
    "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN",
    "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN",
    "Detroit Lions": "DET",
    "Green Bay Packers": "GB",
    "Houston Texans": "HOU",
    "Indianapolis Colts": "IND",
    "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV",
    "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LAR",
    "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN",
    "New England Patriots": "NE",
    "New Orleans Saints": "NO",
    "New York Giants": "NYG",
    "New York Jets": "NYJ",
    "Philadelphia Eagles": "PHI",
    "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA",
    "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN",
    "Washington Commanders": "WAS",
}


# ---------------------------------------------------------
# LOAD WORKBOOK
# ---------------------------------------------------------
@st.cache_data
def load_redzone_data():
    if not REDZONE_FILE.exists():
        raise FileNotFoundError(
            f"Could not find '{REDZONE_FILE.name}' in:\n{REDZONE_FILE.parent}"
        )

    players = pd.read_excel(
        REDZONE_FILE,
        sheet_name="2025 Week by Week",
    )

    if not REDZONE_SCHEDULE_FILE.exists():
        raise FileNotFoundError(
            f"Could not find '{REDZONE_SCHEDULE_FILE.name}' in:\n{REDZONE_SCHEDULE_FILE.parent}"
        )

    schedule = pd.read_excel(
        REDZONE_SCHEDULE_FILE,
        sheet_name="Sheet1",
    )

    rankings = pd.read_excel(
        REDZONE_FILE,
        sheet_name="Defense Rankings",
    )

    # Clean column names
    players.columns = players.columns.map(str).str.strip()
    schedule.columns = schedule.columns.map(str).str.strip()
    rankings.columns = rankings.columns.map(str).str.strip()

    # Clean player fields
    players["Player"] = players["Player"].astype(str).str.strip()
    players["Position"] = (
        players["Position"].astype(str).str.upper().str.strip()
    )
    players["Team"] = (
        players["Team"].astype(str).str.upper().str.strip()
    )

    # Clean schedule fields
    schedule["Team"] = (
        schedule["Team"].astype(str).str.upper().str.strip()
    )
    schedule["Opp"] = (
        schedule["Opp"].astype(str).str.upper().str.strip()
    )
    schedule["Week"] = pd.to_numeric(
        schedule["Week"],
        errors="coerce",
    )

    if "Home/Away" in schedule.columns:
        schedule["Home/Away"] = (
            schedule["Home/Away"].astype(str).str.strip()
        )

    # Add abbreviations to defensive rankings
    rankings["Abbreviation"] = (
        rankings["Team"]
        .astype(str)
        .str.strip()
        .map(TEAM_ABBREVIATIONS)
    )

    # Convert relevant numeric columns
    for column in ["ADP", "AVG"]:
        if column in players.columns:
            players[column] = pd.to_numeric(
                players[column],
                errors="coerce",
            )

    for column in ["RB Rank", "WR Rank", "TE Rank"]:
        if column in rankings.columns:
            rankings[column] = pd.to_numeric(
                rankings[column],
                errors="coerce",
            )

    return players, schedule, rankings


# ---------------------------------------------------------
# POSITION-BASED MATCHUP SETTINGS
# ---------------------------------------------------------
def get_matchup_columns(position):
    """
    Select the correct defensive ranking based on player position.
    """

    position = str(position).upper().strip()

    if position == "RB":
        return {
            "rank_column": "RB Rank",
            "rank_label": "RB D Rank",
        }

    if position == "TE":
        return {
            "rank_column": "TE Rank",
            "rank_label": "TE D Rank",
        }

    # WR uses WR defensive rank.
    # QB temporarily uses WR defensive rank as a passing-defense proxy.
    return {
        "rank_column": "WR Rank",
        "rank_label": (
            "WR D Rank"
            if position == "WR"
            else "Pass D Rank"
        ),
    }


# ---------------------------------------------------------
# CREATE ONE PLAYER'S WEEKLY TABLE
# ---------------------------------------------------------
def create_player_table(player_row, schedule, rankings):
    player_position = player_row["Position"]
    player_team = player_row["Team"]

    matchup_columns = get_matchup_columns(player_position)

    # Get Weeks 1-17 for the player's NFL team
    player_schedule = schedule[
        schedule["Team"] == player_team
    ].copy()

    player_schedule = player_schedule[
        player_schedule["Week"].between(1, 17)
    ].copy()

    player_schedule = player_schedule.sort_values("Week")

    # Merge the appropriate defensive rank onto each opponent
    ranking_lookup = rankings[
        ["Abbreviation", matchup_columns["rank_column"]]
    ].drop_duplicates(subset="Abbreviation")

    ranking_lookup = ranking_lookup.rename(
        columns={
            "Abbreviation": "Opp",
            matchup_columns["rank_column"]:
                matchup_columns["rank_label"],
        }
    )

    result = player_schedule.merge(
        ranking_lookup,
        on="Opp",
        how="left",
    )

    # Pull the player's fantasy score for each week
    fantasy_points = []

    for week in result["Week"]:
        possible_columns = [str(int(week)), int(week)]
        week_value = 0

        for column in possible_columns:
            if column in player_row.index:
                week_value = player_row[column]
                break

        week_value = pd.to_numeric(
            week_value,
            errors="coerce",
        )

        if pd.isna(week_value):
            week_value = 0

        fantasy_points.append(round(float(week_value), 1))

    result["Fantasy Pts"] = fantasy_points

    # Clear matchup information for bye weeks
    bye_mask = result["Opp"] == "BYE"

    result.loc[
        bye_mask,
        matchup_columns["rank_label"],
    ] = pd.NA

    result.loc[bye_mask, "Fantasy Pts"] = 0

    # Create readable home/away matchup labels
    result["Matchup"] = result.apply(
        lambda row: (
            "BYE"
            if row["Opp"] == "BYE"
            else (
                f"✈️ @ {row['Opp']}"
                if str(row.get("Home/Away", "")).lower() == "away"
                else f"🏠 vs {row['Opp']}"
            )
        ),
        axis=1,
    )

    final_columns = [
        "Week",
        "Matchup",
        matchup_columns["rank_label"],
        "Fantasy Pts",
    ]

    return result[final_columns], matchup_columns


# ---------------------------------------------------------
# HOME/AWAY AND SCHEDULE RANKINGS
# ---------------------------------------------------------
@st.cache_data
def calculate_position_rankings(
    players,
    schedule,
    rankings,
    selected_position,
):
    """
    Compare every player at the selected position.

    Home/Away rank:
        Higher fantasy average = better rank.

    Hardest schedule rank:
        Lower average defensive rank = harder schedule.
        Therefore, #1 is the hardest schedule.
    """

    position_players = players[
        players["Position"] == selected_position
    ].copy()

    results = []

    for _, comparison_player in position_players.iterrows():
        try:
            player_table, columns = create_player_table(
                comparison_player,
                schedule,
                rankings,
            )
        except (KeyError, ValueError, TypeError):
            continue

        home_games = player_table[
            player_table["Matchup"].str.startswith(
                "🏠",
                na=False,
            )
        ].copy()

        away_games = player_table[
            player_table["Matchup"].str.startswith(
                "✈️",
                na=False,
            )
        ].copy()

        non_bye_games = player_table[
            player_table["Matchup"] != "BYE"
        ].copy()

        rank_column = columns["rank_label"]

        home_average = home_games["Fantasy Pts"].mean()
        away_average = away_games["Fantasy Pts"].mean()
        schedule_average = non_bye_games[rank_column].mean()

        results.append(
            {
                "Player": comparison_player["Player"],
                "Team": comparison_player["Team"],
                "Position": comparison_player["Position"],
                "Home Average": home_average,
                "Away Average": away_average,
                "Schedule Average Rank": schedule_average,
            }
        )

    ranking_df = pd.DataFrame(results)

    if ranking_df.empty:
        return ranking_df

    ranking_df["Home Position Rank"] = (
        ranking_df["Home Average"]
        .rank(
            ascending=False,
            method="min",
            na_option="bottom",
        )
    )

    ranking_df["Away Position Rank"] = (
        ranking_df["Away Average"]
        .rank(
            ascending=False,
            method="min",
            na_option="bottom",
        )
    )

    ranking_df["Hardest Schedule Rank"] = (
        ranking_df["Schedule Average Rank"]
        .rank(
            ascending=True,
            method="min",
            na_option="bottom",
        )
    )

    return ranking_df


# ---------------------------------------------------------
# TABLE COLORING
# ---------------------------------------------------------
def color_defensive_rank(value):
    """
    Lower rank = tougher defense.
    Higher rank = easier fantasy matchup.
    """

    if pd.isna(value):
        return ""

    try:
        rank = float(value)
    except (TypeError, ValueError):
        return ""

    if rank >= 25:
        return "background-color: #b7e1cd; color: #0b4128;"

    if rank >= 17:
        return "background-color: #d9ead3; color: #274e13;"

    if rank >= 9:
        return "background-color: #fff2cc; color: #7f6000;"

    return "background-color: #f4cccc; color: #660000;"




# ============================================================
# HISTORICAL METRICS
# ============================================================
def tier_of_rank(rank):
    if pd.isna(rank): return None
    r = int(rank)
    if r <= 2: return "Top 2"
    if r <= 5: return "3-5"
    if r <= 10: return "6-10"
    if r <= 15: return "11-15"
    if r <= 25: return "16-25"
    if r <= 35: return "26-35"
    if r <= 50: return "36-50"
    if r <= 65: return "51-65"
    if r <= 80: return "66-80"
    return None

FINISH_BENCH = finish.set_index("POS").to_dict("index")

# Positional ADP inside each historical season
hist["Draft Pos Rank"] = hist.groupby(["Year","Position"])["ADP"].rank(method="first", ascending=True)
hist["Draft Tier"] = hist["Draft Pos Rank"].apply(tier_of_rank)

def draft_expected(row):
    tier = row["Draft Tier"]
    if tier is None: return np.nan
    return FINISH_BENCH.get(row["Position"], {}).get(tier, np.nan)

hist["Expected PPG at Cost"] = hist.apply(draft_expected, axis=1)
hist["Value %"] = hist["AVG"] / hist["Expected PPG at Cost"] * 100
hist["Worth It"] = hist["Value %"] >= 100
hist["Bust"] = hist["Value %"] < 80

# Separate END-OF-SEASON benchmark used for player-history analysis.
# Example: if a player finishes WR5, use the WR 3-5 value from Finish Points.
hist["Finish Tier"] = hist["RK"].apply(tier_of_rank)

def finish_tier_expected(row):
    tier = row["Finish Tier"]
    if tier is None:
        return np.nan
    return FINISH_BENCH.get(row["Position"], {}).get(tier, np.nan)

hist["Expected PPG at Finish"] = hist.apply(finish_tier_expected, axis=1)
hist["Finish Benchmark %"] = hist["AVG"] / hist["Expected PPG at Finish"] * 100

# Player-history ROI metrics:
# Positive Rank Return = player finished BETTER than his positional draft slot.
# Example: drafted RB10, finished RB4 => +6.
hist["Positional Rank Return"] = hist["Draft Pos Rank"] - hist["RK"]
hist["Met Finish Benchmark"] = hist["Finish Benchmark %"] >= 100
hist["Met Draft Rank"] = hist["RK"] <= hist["Draft Pos Rank"]

# Final player-history Worth It requires BOTH:
# 1) per-game production met the benchmark for where he finished, and
# 2) end-of-season rank met or beat the positional draft slot.
hist["Overall Worth It"] = hist["Met Finish Benchmark"] & hist["Met Draft Rank"]

def worth_it_reason(row):
    if pd.isna(row["Draft Pos Rank"]) or pd.isna(row["RK"]):
        return "Insufficient data"
    if row["Overall Worth It"]:
        return "Met scoring benchmark and returned draft rank"
    if not row["Met Draft Rank"] and not row["Met Finish Benchmark"]:
        return "Missed both scoring benchmark and draft-rank expectation"
    if not row["Met Draft Rank"]:
        return "Good per-game scoring, but finished below draft position"
    return "Finished at/above draft slot, but PPG missed finish-tier benchmark"

hist["Worth It Reason"] = hist.apply(worth_it_reason, axis=1)

# Exact end-of-season rank PPG: "WR18" = historical players who FINISHED WR18
finish_rank = (
    hist.dropna(subset=["Position","RK","AVG"])
    .groupby(["Position","RK"])
    .agg(Expected_Finish_PPG=("AVG","mean"), Finish_Sample=("Player","count"))
    .reset_index()
)

finish_ppg_lookup = finish_rank.set_index(["Position","RK"])["Expected_Finish_PPG"].to_dict()
finish_n_lookup = finish_rank.set_index(["Position","RK"])["Finish_Sample"].to_dict()

def finish_expected_ppg(pos, rank):
    if pd.isna(rank): return np.nan
    key = (pos, int(rank))
    if key in finish_ppg_lookup:
        return finish_ppg_lookup[key]
    tier = tier_of_rank(rank)
    return FINISH_BENCH.get(pos, {}).get(tier, np.nan)

# Historical draft-tier profile: how players drafted in a positional range actually performed.
tier_profile = (
    hist.dropna(subset=["Position","Draft Tier"])
    .groupby(["Position","Draft Tier"])
    .agg(
        Hist_PPG=("AVG","mean"),
        Worth_Rate=("Worth It","mean"),
        Avg_Value=("Value %","mean"),
        Boom10=("Boom 10","mean"),
        Boom15=("Boom 15","mean"),
        Boom20=("Boom 20","mean"),
        Boom25=("Boom 25","mean"),
        Boom30=("Boom 30","mean"),
        Sample=("Player","count")
    )
    .reset_index()
)
tier_profile["Worth_Rate"] *= 100

profile_lookup = tier_profile.set_index(["Position","Draft Tier"]).to_dict("index")

def candidate_profile(pos, pos_rank):
    tier = tier_of_rank(pos_rank)
    prof = profile_lookup.get((pos, tier), {})
    # Expected production for current positional slot is based on END-OF-SEASON rank outcomes.
    ppg = finish_expected_ppg(pos, pos_rank)
    return {
        "Tier": tier,
        "Expected PPG": ppg,
        "Worth %": prof.get("Worth_Rate", np.nan),
        "Value %": prof.get("Avg_Value", np.nan),
        "Boom 10 Games": prof.get("Boom10", np.nan),
        "Boom 15 Games": prof.get("Boom15", np.nan),
        "Boom 20 Games": prof.get("Boom20", np.nan),
        "Boom 25 Games": prof.get("Boom25", np.nan),
        "Boom 30 Games": prof.get("Boom30", np.nan),
        "Hist Sample": prof.get("Sample", 0),
    }

profiles = []
for _, r in adp26.iterrows():
    p = candidate_profile(r["Position"], r["Pos Rank"])
    profiles.append(p)
profiles = pd.DataFrame(profiles)
pool = pd.concat([adp26.reset_index(drop=True), profiles], axis=1)


# ============================================================
# 2026 ROUND MARKET HELPERS
# ============================================================
market_by_round = market.set_index("Round")[["QB","RB","WR","TE"]].sort_index()

def taken_end_of_round(round_num, position):
    if round_num <= 0:
        return 0
    if round_num not in market_by_round.index:
        return np.nan
    val = market_by_round.loc[round_num, position]
    return int(val) if pd.notna(val) else np.nan

def available_entering_round(round_num, position):
    prev = taken_end_of_round(round_num - 1, position)
    if pd.isna(prev):
        return np.nan
    return int(prev) + 1

def available_next_round(round_num, position):
    curr = taken_end_of_round(round_num, position)
    if pd.isna(curr):
        return np.nan
    return int(curr) + 1

def boom_metric_for_threshold(threshold):
    return f"Boom {int(threshold)} Games"

def round_position_boom_summary(round_num):
    x = hist[hist["Round"] == round_num].copy()
    if x.empty:
        return pd.DataFrame()

    rows = []
    for pos, g in x.groupby("Position"):
        rows.append({
            "Position": pos,
            "Players": len(g),
            "Boom 10 Games": pd.to_numeric(g["Boom 10"], errors="coerce").mean() if "Boom 10" in g.columns else np.nan,
            "Boom 15 Games": pd.to_numeric(g["Boom 15"], errors="coerce").mean() if "Boom 15" in g.columns else np.nan,
            "Boom 20 Games": pd.to_numeric(g["Boom 20"], errors="coerce").mean() if "Boom 20" in g.columns else np.nan,
            "Boom 25 Games": pd.to_numeric(g["Boom 25"], errors="coerce").mean() if "Boom 25" in g.columns else np.nan,
            "Boom 30 Games": pd.to_numeric(g["Boom 30"], errors="coerce").mean() if "Boom 30" in g.columns else np.nan,
            "Worth-It %": g["Worth It"].mean() * 100 if "Worth It" in g.columns else np.nan,
            "Avg Value %": g["Value %"].mean() if "Value %" in g.columns else np.nan,
            "Avg PPG": g["AVG"].mean()
        })

    return pd.DataFrame(rows)

# ============================================================
# SCORING
# ============================================================
def round_phase(round_num):
    if round_num <= 5: return "early"
    if round_num <= 12: return "middle"
    return "late"

def minmax(series):
    s = pd.to_numeric(series, errors="coerce")
    if s.notna().sum() < 2 or s.max() == s.min():
        return pd.Series(50.0, index=s.index)
    return ((s - s.min()) / (s.max() - s.min()) * 100).fillna(50)

def boom_score(df, round_num, style):
    # Boom 10/15/20/25/30 are COUNTS OF GAMES reaching that spike-game threshold.
    # Example: Boom 25 = 3 means three 25+ point games.
    # Later rounds intentionally emphasize counts of the bigger spike weeks.
    if round_num <= 5:
        raw = (
            .50*df["Boom 15 Games"].fillna(0) +
            .35*df["Boom 20 Games"].fillna(0) +
            .15*df["Boom 25 Games"].fillna(0)
        )
    elif round_num <= 12:
        raw = (
            .20*df["Boom 15 Games"].fillna(0) +
            .40*df["Boom 20 Games"].fillna(0) +
            .30*df["Boom 25 Games"].fillna(0) +
            .10*df["Boom 30 Games"].fillna(0)
        )
    else:
        raw = (
            .10*df["Boom 20 Games"].fillna(0) +
            .40*df["Boom 25 Games"].fillna(0) +
            .50*df["Boom 30 Games"].fillna(0)
        )
    return minmax(raw)

def roster_counts(roster):
    counts = {"QB":0,"RB":0,"WR":0,"TE":0}
    for pos in roster:
        if pos in counts: counts[pos] += 1
    return counts

def roster_need_multiplier(position, counts, round_num, picks_left):
    # Hard-ish protection against structurally unusable builds
    if counts[position] >= ROSTER_MAX[position]:
        return 0.05

    remaining_need = sum(max(0, ROSTER_MIN[p] - counts[p]) for p in ROSTER_MIN)
    need_this = max(0, ROSTER_MIN[position] - counts[position])

    mult = 1.0

    # Reward filling unmet minimums more as draft gets later
    if need_this > 0:
        mult += 0.08 + (round_num / ROUNDS) * 0.30

    # If picks left are getting close to required minimum slots, strongly enforce need
    if picks_left <= remaining_need + 2 and need_this > 0:
        mult += 0.60

    # Best-ball structural preferences
    if position == "WR":
        # 3 WR + FLEX makes depth particularly valuable
        if counts["WR"] < 5: mult += 0.12
        if round_num >= 9 and counts["WR"] < 7: mult += 0.15
    if position == "QB":
        # One QB matters a lot; the second is depth; the third should be rare.
        if counts["QB"] == 0:
            if round_num >= 8:
                mult += 0.25
        elif counts["QB"] == 1:
            # Mildly discourage taking QB2 too early.
            if round_num <= 8:
                mult -= 0.20
            elif round_num <= 12:
                mult -= 0.08
        elif counts["QB"] == 2:
            # Third QB is generally a late-round contingency only.
            if round_num < 17:
                return 0.03
            mult -= 0.35
        else:
            # Never intentionally draft QB4.
            return 0.01
    if position == "TE":
        if counts["TE"] == 0 and round_num >= 9: mult += 0.18
        if counts["TE"] >= 2 and round_num < 16: mult -= 0.12
    if position == "RB":
        if counts["RB"] >= 5 and round_num < 15: mult -= 0.08

    return max(mult, 0.05)

def score_candidates(cands, round_num, style, roster_positions):
    x = cands.copy()
    phase = round_phase(round_num)
    w = STYLE_WEIGHTS[style][phase]

    x["PPG Score"] = minmax(x["Expected PPG"])
    x["Worth Score"] = x["Worth %"].fillna(50).clip(0,100)
    x["Value Score"] = minmax(x["Value %"].fillna(100))
    x["Boom Score"] = boom_score(x, round_num, style)

    x["Base Score"] = (
        w["ppg"] * x["PPG Score"] +
        w["worth"] * x["Worth Score"] +
        w["boom"] * x["Boom Score"] +
        w["value"] * x["Value Score"]
    )

    counts = roster_counts(roster_positions)
    picks_left = ROUNDS - len(roster_positions)
    x["Roster Multiplier"] = x["Position"].apply(
        lambda p: roster_need_multiplier(p, counts, round_num, picks_left)
    )
    x["Optimizer Score"] = x["Base Score"] * x["Roster Multiplier"]
    return x.sort_values("Optimizer Score", ascending=False)

# ============================================================
# SNAKE PICKS + AVAILABILITY
# ============================================================
def snake_picks(slot, teams=12, rounds=20):
    picks = []
    for rnd in range(1, rounds+1):
        if rnd % 2 == 1:
            overall = (rnd-1)*teams + slot
        else:
            overall = rnd*teams - slot + 1
        picks.append(overall)
    return picks

def likely_available(current_pool, overall_pick, window=10):
    # ADP is not deterministic. Include players whose ADP is around or later than the pick,
    # plus a small slide window to allow realistic fallers.
    low = max(1, overall_pick - window)
    return current_pool[current_pool["Rank"] >= low].copy()

# ============================================================
# AUTO DRAFT PLAN
# ============================================================
def build_plan(slot, style, forced_name, adp_window, locked_round=None, locked_player=None):
    picks = snake_picks(slot)
    available = pool.copy()
    roster_positions = []
    roster_players = []
    rows = []
    forced = FORCED_BUILDS.get(forced_name, {})

    for rnd, overall_pick in enumerate(picks, start=1):
        cands = likely_available(available, overall_pick, adp_window)

        # If somehow nothing meets the window, use remaining pool.
        if cands.empty:
            cands = available.copy()

        # Best-ball QB guardrails for the AUTO plan.
        # A locked player can still override these rules intentionally.
        qb_count = roster_positions.count("QB")
        last_pos = roster_positions[-1] if roster_positions else None

        if not (
            locked_round is not None and
            locked_player and
            rnd == int(locked_round)
        ):
            # Never take QBs back-to-back in the automatic plan.
            if last_pos == "QB":
                non_qb = cands[cands["Position"] != "QB"]
                if not non_qb.empty:
                    cands = non_qb

            # Do not take QB3 before Round 17.
            if qb_count >= 2 and rnd < 17:
                non_qb = cands[cands["Position"] != "QB"]
                if not non_qb.empty:
                    cands = non_qb

            # Never auto-draft QB4.
            if qb_count >= 3:
                non_qb = cands[cands["Position"] != "QB"]
                if not non_qb.empty:
                    cands = non_qb

        # Optional exact player lock overrides positional opening strategy.
        locked_this_round = (
            locked_round is not None and
            locked_player and
            rnd == int(locked_round) and
            locked_player in available["Player"].values
        )

        if locked_this_round:
            locked_cands = available[available["Player"] == locked_player].copy()
            scored = score_candidates(locked_cands, rnd, style, roster_positions)
            scored["ADP Proximity"] = 1.0
            scored["Final Score"] = scored["Optimizer Score"]
            choice = scored.iloc[0]
        else:
            # Forced opening strategies
            forced_pos = forced.get(rnd)
            if forced_pos:
                forced_cands = cands[cands["Position"] == forced_pos]
                if not forced_cands.empty:
                    cands = forced_cands

            scored = score_candidates(cands, rnd, style, roster_positions)

            # Prefer players not absurdly far past pick by adding mild ADP proximity bonus
            scored["ADP Proximity"] = np.exp(-np.maximum(scored["Rank"] - overall_pick, 0) / 30.0)
            scored["Final Score"] = scored["Optimizer Score"] * (0.90 + 0.10*scored["ADP Proximity"])

            choice = scored.sort_values("Final Score", ascending=False).iloc[0]

        roster_positions.append(choice["Position"])
        roster_players.append(choice["Player"])

        rows.append({
            "Round": rnd,
            "Overall Pick": overall_pick,
            "Player": choice["Player"],
            "Position": choice["Position"],
            "2026 Rank": int(choice["Rank"]) if pd.notna(choice["Rank"]) else np.nan,
            "Positional Rank": choice["POS"],
            "Pos Rank": int(choice["Pos Rank"]) if pd.notna(choice["Pos Rank"]) else np.nan,
            "Expected PPG": choice["Expected PPG"],
            "Worth %": choice["Worth %"],
            "Boom 20 Games": choice["Boom 20 Games"],
            "Boom 25 Games": choice["Boom 25 Games"],
            "Boom 30 Games": choice["Boom 30 Games"],
            "Optimizer Score": choice["Final Score"],
            "Locked": bool(locked_this_round),
        })

        available = available[available["Player"] != choice["Player"]].copy()

    return pd.DataFrame(rows)


# ============================================================
# 14-WEEK BEST-BALL SCORE PROJECTION
# ============================================================
WEEK_COLS = [c for c in range(1, 15) if c in hist.columns]

@st.cache_data(show_spinner=False)
def build_weekly_distribution_lookup():
    lookup = {}

    for pos in ["QB", "RB", "WR", "TE"]:
        pos_hist = hist[hist["Position"] == pos].copy()

        ranks = sorted(
            pd.to_numeric(pos_hist["RK"], errors="coerce")
            .dropna()
            .astype(int)
            .unique()
        )

        for r in ranks:
            same = pos_hist[pos_hist["RK"] == r].copy()

            if len(same) < 2:
                same = pos_hist[
                    pd.to_numeric(pos_hist["RK"], errors="coerce")
                    .between(max(1, r - 2), r + 2)
                ].copy()

            if same.empty:
                tier = tier_of_rank(r)
                same = pos_hist[
                    pos_hist["RK"].apply(tier_of_rank) == tier
                ].copy()

            vals = []
            for c in WEEK_COLS:
                s = pd.to_numeric(same[c], errors="coerce")
                vals.extend(s.dropna().tolist())

            arr = np.array(
                [v for v in vals if np.isfinite(v) and v >= 0],
                dtype=float
            )
            lookup[(pos, r)] = arr

    return lookup

WEEKLY_DIST_LOOKUP = build_weekly_distribution_lookup()

def historical_weekly_pool(position, finish_rank_value):
    if pd.isna(finish_rank_value):
        return np.array([])

    r = int(finish_rank_value)

    if (position, r) in WEEKLY_DIST_LOOKUP:
        return WEEKLY_DIST_LOOKUP[(position, r)]

    # fallback to nearest rank already cached
    candidates = [
        key for key in WEEKLY_DIST_LOOKUP
        if key[0] == position
    ]
    if not candidates:
        return np.array([])

    nearest = min(candidates, key=lambda k: abs(k[1] - r))
    return WEEKLY_DIST_LOOKUP.get(nearest, np.array([]))

def fallback_weekly_params(row):
    mean = row.get("Expected PPG", np.nan)
    if pd.isna(mean):
        mean = 8.0
    # Use boom tendency to create a reasonable volatility estimate.
    boom20_games = row.get("Boom 20 Games", np.nan)
    boom25_games = row.get("Boom 25 Games", np.nan)
    spike_games = np.nanmean([boom20_games, boom25_games])
    if pd.isna(spike_games):
        spike_games = 1.5

    # More 20+/25+ spike games implies a wider weekly distribution.
    volatility_bonus = min(max(spike_games, 0), 8) * 0.045
    sd = max(3.0, mean * (0.30 + volatility_bonus))
    return float(mean), float(sd)

def draw_week_score(row, rng):
    pos_rank = row.get("Pos Rank", np.nan)

    # Backward-compatible fallback: parse a display label like WR18 / RB4 / TE2.
    if pd.isna(pos_rank):
        label = str(row.get("Positional Rank", ""))
        match = re.search(r"(\d+)", label)
        if match:
            pos_rank = int(match.group(1))

    vals = historical_weekly_pool(row["Position"], pos_rank)
    if len(vals) >= 8:
        return float(rng.choice(vals))

    mean, sd = fallback_weekly_params(row)
    return float(max(0, rng.normal(mean, sd)))

def best_ball_week_score(player_scores):
    """
    player_scores: list of dicts with Position and Score.
    Scores exactly: 1 QB, 2 RB, 3 WR, 1 TE, 1 FLEX (RB/WR/TE).
    """
    frame = pd.DataFrame(player_scores)

    total = 0.0
    used = set()

    requirements = [("QB", 1), ("RB", 2), ("WR", 3), ("TE", 1)]

    for pos, n in requirements:
        eligible = frame[(frame["Position"] == pos) & (~frame.index.isin(used))]
        chosen = eligible.nlargest(n, "Score")
        if len(chosen) < n:
            return np.nan
        total += chosen["Score"].sum()
        used.update(chosen.index.tolist())

    flex = frame[
        frame["Position"].isin(["RB","WR","TE"]) &
        (~frame.index.isin(used))
    ]
    if flex.empty:
        return np.nan

    total += flex["Score"].max()
    return float(total)

def project_roster_14_weeks(plan_records, simulations=250, seed=42):
    """
    Monte Carlo projection. Each 2026 player's weekly distribution is mapped
    to historical weekly outcomes from players who finished at the same
    positional rank.
    """
    plan_df = pd.DataFrame(plan_records)
    rng = np.random.default_rng(seed)
    totals = []

    for _ in range(simulations):
        season_total = 0.0
        valid_season = True

        for week in range(1, 15):
            player_scores = []
            for _, row in plan_df.iterrows():
                player_scores.append({
                    "Player": row["Player"],
                    "Position": row["Position"],
                    "Score": draw_week_score(row, rng)
                })

            weekly = best_ball_week_score(player_scores)
            if pd.isna(weekly):
                valid_season = False
                break
            season_total += weekly

        if valid_season:
            totals.append(season_total)

    if not totals:
        return {
            "mean": np.nan, "median": np.nan,
            "p25": np.nan, "p75": np.nan, "p90": np.nan,
            "weekly_mean": np.nan
        }

    arr = np.array(totals, dtype=float)
    return {
        "mean": float(arr.mean()),
        "median": float(np.median(arr)),
        "p25": float(np.percentile(arr, 25)),
        "p75": float(np.percentile(arr, 75)),
        "p90": float(np.percentile(arr, 90)),
        "weekly_mean": float(arr.mean() / 14.0)
    }



# ============================================================
# ROOKIE ANALYSIS HELPERS
# ============================================================
def rookie_analysis_table():
    rook = hist[hist["Is Rookie"]].copy()

    if "Positional Rank Return" not in rook.columns:
        rook["Positional Rank Return"] = rook["Draft Pos Rank"] - rook["RK"]

    if "Overall Worth It" not in rook.columns:
        rook["Overall Worth It"] = (
            (rook["Finish Benchmark %"] >= 100) &
            (rook["RK"] <= rook["Draft Pos Rank"])
        )

    if "Met Draft Rank" not in rook.columns:
        rook["Met Draft Rank"] = rook["RK"] <= rook["Draft Pos Rank"]

    return rook

def render_redzone_tab():
    st.header("🏟️ RedZone Analytics — 2025 NFL Player Personnel")

    st.caption(
        "Weekly fantasy production, home/away splits, opponents, "
        "defensive rankings, and positional schedule difficulty."
    )

    try:
        players_df, schedule_df, rankings_df = load_redzone_data()
    except Exception as error:
        st.error(f"Unable to load workbook: {error}")
        return


    # ---------------------------------------------------------
    # SIDEBAR FILTERS
    # ---------------------------------------------------------
    st.subheader("Player Filters")

    available_positions = sorted(
        players_df["Position"].dropna().unique().tolist()
    )

    selected_positions = st.multiselect(
        "Position",
        options=available_positions,
        default=available_positions,
        key="redzone_positions",
    )

    available_teams = sorted(
        players_df["Team"].dropna().unique().tolist()
    )

    selected_teams = st.multiselect(
        "Team",
        options=available_teams,
        default=available_teams,
        key="redzone_teams",
    )


    filtered_players = players_df[
        players_df["Position"].isin(selected_positions)
        & players_df["Team"].isin(selected_teams)
    ].copy()

    filtered_players = filtered_players.sort_values(
        ["ADP", "Player"],
        na_position="last",
    )

    player_names = filtered_players["Player"].dropna().tolist()

    if not player_names:
        st.warning("No players match the selected filters.")
        return


    selected_player = st.selectbox(
        "Search or select a player",
        options=player_names,
        key="redzone_player",
    )

    player_row = filtered_players[
        filtered_players["Player"] == selected_player
    ].iloc[0]

    selected_position = player_row["Position"]


    # ---------------------------------------------------------
    # PLAYER INFORMATION
    # ---------------------------------------------------------
    col1, col2, col3, col4, col5 = st.columns(5)

    col1.metric("Player", player_row["Player"])
    col2.metric("Position", selected_position)
    col3.metric("Team", player_row["Team"])

    adp = pd.to_numeric(
        player_row.get("ADP"),
        errors="coerce",
    )

    average = pd.to_numeric(
        player_row.get("AVG"),
        errors="coerce",
    )

    col4.metric(
        "ADP",
        f"{adp:.1f}" if pd.notna(adp) else "—",
    )

    col5.metric(
        "Fantasy Average",
        f"{average:.1f}" if pd.notna(average) else "—",
    )


    # ---------------------------------------------------------
    # SELECTED PLAYER WEEKLY DATA
    # ---------------------------------------------------------
    weekly_table, matchup_columns = create_player_table(
        player_row,
        schedule_df,
        rankings_df,
    )

    rank_column = matchup_columns["rank_label"]

    non_bye_games = weekly_table[
        weekly_table["Matchup"] != "BYE"
    ].copy()

    home_games = weekly_table[
        weekly_table["Matchup"].str.startswith(
            "🏠",
            na=False,
        )
    ].copy()

    away_games = weekly_table[
        weekly_table["Matchup"].str.startswith(
            "✈️",
            na=False,
        )
    ].copy()

    home_average = home_games["Fantasy Pts"].mean()
    away_average = away_games["Fantasy Pts"].mean()

    home_average = (
        0.0
        if pd.isna(home_average)
        else float(home_average)
    )

    away_average = (
        0.0
        if pd.isna(away_average)
        else float(away_average)
    )


    # ---------------------------------------------------------
    # POSITION RANKINGS
    # ---------------------------------------------------------
    position_rankings = calculate_position_rankings(
        players_df,
        schedule_df,
        rankings_df,
        selected_position,
    )

    selected_ranking_rows = position_rankings[
        position_rankings["Player"] == selected_player
    ]

    position_player_count = len(position_rankings)

    if not selected_ranking_rows.empty:
        selected_ranking = selected_ranking_rows.iloc[0]

        home_position_rank = int(
            selected_ranking["Home Position Rank"]
        )

        away_position_rank = int(
            selected_ranking["Away Position Rank"]
        )

        hardest_schedule_rank = int(
            selected_ranking["Hardest Schedule Rank"]
        )

        schedule_average_rank = selected_ranking[
            "Schedule Average Rank"
        ]
    else:
        home_position_rank = None
        away_position_rank = None
        hardest_schedule_rank = None
        schedule_average_rank = pd.NA


    if home_average > away_average:
        better_location = "🏠 Home"
    elif away_average > home_average:
        better_location = "✈️ Away"
    else:
        better_location = "Even"


    # ---------------------------------------------------------
    # HOME VS AWAY DISPLAY
    # ---------------------------------------------------------
    st.subheader("Home vs Away Performance")

    home_col, away_col, better_col = st.columns(3)

    home_col.metric(
        "🏠 Home Average",
        f"{home_average:.1f} pts",
    )

    home_col.caption(
        (
            f"{selected_position} rank "
            f"#{home_position_rank} of {position_player_count}"
        )
        if home_position_rank is not None
        else "Position rank unavailable"
    )

    away_col.metric(
        "✈️ Away Average",
        f"{away_average:.1f} pts",
    )

    away_col.caption(
        (
            f"{selected_position} rank "
            f"#{away_position_rank} of {position_player_count}"
        )
        if away_position_rank is not None
        else "Position rank unavailable"
    )

    better_col.metric(
        "Better Split",
        better_location,
    )

    difference = abs(home_average - away_average)

    better_col.caption(
        f"{difference:.1f} points per game difference"
    )


    # ---------------------------------------------------------
    # SCHEDULE DIFFICULTY DISPLAY
    # ---------------------------------------------------------
    st.subheader("Schedule Difficulty")

    schedule_col1, schedule_col2 = st.columns(2)

    schedule_col1.metric(
        f"Hardest Schedule Among {selected_position}s",
        (
            f"#{hardest_schedule_rank} of {position_player_count}"
            if hardest_schedule_rank is not None
            else "—"
        ),
    )

    schedule_col1.caption(
        "#1 represents the hardest schedule."
    )

    schedule_col2.metric(
        "Average Opponent D Rank",
        (
            f"{schedule_average_rank:.1f}"
            if pd.notna(schedule_average_rank)
            else "—"
        ),
    )

    schedule_col2.caption(
        "A lower average means tougher opposing defenses."
    )


    # ---------------------------------------------------------
    # WEEKLY MATCHUP TABLE
    # ---------------------------------------------------------
    st.subheader(f"{selected_player}: Weekly Matchups")

    styled_table = (
        weekly_table.style
        .map(
            color_defensive_rank,
            subset=[rank_column],
        )
        .format(
            {
                rank_column: "{:.0f}",
                "Fantasy Pts": "{:.1f}",
            },
            na_rep="—",
        )
    )

    st.dataframe(
        styled_table,
        use_container_width=True,
        hide_index=True,
        height=640,
    )


    # ---------------------------------------------------------
    # MATCHUP SUMMARY
    # ---------------------------------------------------------
    valid_rank_rows = non_bye_games.dropna(
        subset=[rank_column]
    )

    if not valid_rank_rows.empty:
        easiest_matchup = valid_rank_rows.loc[
            valid_rank_rows[rank_column].idxmax()
        ]

        toughest_matchup = valid_rank_rows.loc[
            valid_rank_rows[rank_column].idxmin()
        ]

        st.subheader("Matchup Summary")

        summary1, summary2, summary3 = st.columns(3)

        summary1.metric(
            "Average Defensive Rank",
            f"{valid_rank_rows[rank_column].mean():.1f}",
        )

        summary2.metric(
            "Easiest Matchup",
            (
                f"Week {int(easiest_matchup['Week'])} "
                f"{easiest_matchup['Matchup']}"
            ),
        )

        summary2.caption(
            f"Defense rank {int(easiest_matchup[rank_column])}"
        )

        summary3.metric(
            "Toughest Matchup",
            (
                f"Week {int(toughest_matchup['Week'])} "
                f"{toughest_matchup['Matchup']}"
            ),
        )

        summary3.caption(
            f"Defense rank {int(toughest_matchup[rank_column])}"
        )


    # ---------------------------------------------------------
    # FANTASY POINTS CHART
    # ---------------------------------------------------------
    st.subheader("Weekly Fantasy Points")

    chart_data = weekly_table.copy()

    fig = px.bar(
        chart_data,
        x="Week",
        y="Fantasy Pts",
        title=f"{selected_player} Weekly Fantasy Points",
        labels={
            "Week": "Week",
            "Fantasy Pts": "Fantasy Points",
        },
        text="Fantasy Pts",
        hover_data={
            "Matchup": True,
            rank_column: True,
            "Week": False,
            "Fantasy Pts": ":.1f",
        },
    )

    fig.update_traces(
        texttemplate="%{text:.1f}",
        textposition="outside",
        cliponaxis=False,
    )

    fig.update_xaxes(
        title_text="Week",
        tickmode="linear",
        tick0=1,
        dtick=1,
        showline=True,
        linewidth=1,
    )

    fig.update_yaxes(
        title_text="Fantasy Points",
        rangemode="tozero",
        showline=True,
        linewidth=1,
    )

    fig.update_layout(
        height=550,
        showlegend=False,
        margin=dict(
            l=80,
            r=30,
            t=70,
            b=80,
        ),
        template="plotly_white",
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
    )


    # ---------------------------------------------------------
    # DOWNLOAD
    # ---------------------------------------------------------
    csv_data = weekly_table.to_csv(
        index=False
    ).encode("utf-8")

    st.download_button(
        label="Download Player Matchups",
        key="redzone_download",
        data=csv_data,
        file_name=(
            selected_player
            .replace(" ", "_")
            .replace("'", "")
            + "_2025_matchups.csv"
        ),
        mime="text/csv",
    )



# ============================================================
# MULTI-YEAR REDZONE ANALYTICS + 2026 PROJECTION
# ============================================================
REDZONE_HISTORY_FILES = {
    2023: Path(__file__).with_name("NFL Project 2023.xlsx"),
    2024: Path(__file__).with_name("NFL Project 2024.xlsx"),
    2025: Path(__file__).with_name("NFL Project 2025.xlsx"),
}

REDZONE_SCHEDULE_FILES = {
    2023: Path(__file__).with_name("2023_NFL_Schedules.xlsx"),
    2024: Path(__file__).with_name("2024_NFL_Schedules.xlsx"),
    2025: Path(__file__).with_name("2025_NFL_Schedules.xlsx"),
    2026: Path(__file__).with_name("2026_NFL_Schedules.xlsx"),
}

YEAR_WEIGHTS = {2023: 0.20, 2024: 0.30, 2025: 0.50}

DEFENSE_POINTS_COLUMNS = {
    "RB": "DKPts vs RBs",
    "WR": "DKPt vs wrs",
    "TE": "DKPt vs TES",
    # Until a true QB-vs-defense field is added, use WR points allowed
    # as a passing-defense proxy for QB projections.
    "QB": "DKPt vs wrs",
}

DEFENSE_RANK_COLUMNS = {
    "RB": "RB Rank",
    "WR": "WR Rank",
    "TE": "TE Rank",
    "QB": "WR Rank",
}


def _clean_team_abbr(value):
    if pd.isna(value):
        return None
    value = str(value).strip().upper()
    aliases = {
        "JAC": "JAX",
        "LA": "LAR",
        "KCD": "KC",
        "WAS": "WAS",
        "WSH": "WAS",
    }
    return aliases.get(value, value)


def _find_sheet_name(xls, preferred, contains=None):
    if preferred in xls.sheet_names:
        return preferred
    if contains:
        matches = [s for s in xls.sheet_names if contains.lower() in s.lower()]
        if matches:
            return matches[0]
    return None


@st.cache_data
def load_redzone_history_year(year):
    """Load historical RedZone inputs for one season.

    Player weekly fantasy scores come directly from the shared
    22-25 Draft Data.xlsx workbook (sheet: 22-25).

    NFL Project YEAR.xlsx is used only for defense-vs-position data,
    while YEAR_NFL_Schedules.xlsx supplies opponent and home/away.
    """
    year = int(year)
    history_file = REDZONE_HISTORY_FILES.get(year)
    schedule_file = REDZONE_SCHEDULE_FILES.get(year)

    if not DATA.exists():
        raise FileNotFoundError(f"Missing {DATA.name}")
    if schedule_file is None or not schedule_file.exists():
        raise FileNotFoundError(f"Missing schedule for {year}: {schedule_file.name if schedule_file else year}")

    # One source of truth for player weekly production.
    all_players = pd.read_excel(DATA, sheet_name="22-25")
    all_players.columns = all_players.columns.map(lambda x: str(x).strip() if not isinstance(x, int) else x)
    if "Year" not in all_players.columns:
        raise ValueError(f"The 22-25 sheet in {DATA.name} does not contain a Year column.")
    year_series = pd.to_numeric(all_players["Year"], errors="coerce")
    players = all_players[year_series == year].copy()

    if players.empty:
        raise ValueError(f"No {year} player rows were found in {DATA.name} / 22-25.")

    schedule = pd.read_excel(schedule_file, sheet_name=0)

    # Defense is optional during setup. If the season workbook exists,
    # read Defense DK Points first, then Defense Rankings as fallback.
    defense = pd.DataFrame()
    if history_file is not None and history_file.exists():
        xls = pd.ExcelFile(history_file)
        defense_sheet = _find_sheet_name(xls, "Defense DK Points", contains="Defense DK")
        ranking_sheet = _find_sheet_name(xls, "Defense Rankings", contains="Defense Rankings")
        if defense_sheet:
            defense = pd.read_excel(history_file, sheet_name=defense_sheet)
        elif ranking_sheet:
            defense = pd.read_excel(history_file, sheet_name=ranking_sheet)

    players.columns = players.columns.map(str).str.strip()
    schedule.columns = schedule.columns.map(str).str.strip()
    defense.columns = defense.columns.map(str).str.strip()

    if "Player" in players.columns:
        players["Player"] = players["Player"].astype(str).str.strip()
    if "Position" in players.columns:
        players["Position"] = players["Position"].astype(str).str.upper().str.strip()
    if "Team" in players.columns:
        players["Team"] = players["Team"].apply(_clean_team_abbr)

    schedule["Team"] = schedule["Team"].apply(_clean_team_abbr)
    schedule["Opp"] = schedule["Opp"].apply(_clean_team_abbr)
    schedule["Week"] = pd.to_numeric(schedule["Week"], errors="coerce")
    if "Home/Away" not in schedule.columns:
        schedule["Home/Away"] = ""
    schedule["Home/Away"] = schedule["Home/Away"].astype("string").str.title().str.strip()

    # Standardize defense team abbreviation.
    if not defense.empty:
        team_col = None
        for candidate in ["Team", "Tm▲", "Tm", "TEAM"]:
            if candidate in defense.columns:
                team_col = candidate
                break
        if team_col:
            if team_col == "Team":
                defense["Abbreviation"] = (
                    defense[team_col].astype(str).str.strip().map(TEAM_ABBREVIATIONS)
                )
                missing = defense["Abbreviation"].isna()
                defense.loc[missing, "Abbreviation"] = defense.loc[missing, team_col].apply(_clean_team_abbr)
            else:
                defense["Abbreviation"] = (
                    defense[team_col].astype(str).str.strip().map(TEAM_ABBREVIATIONS)
                )
                missing = defense["Abbreviation"].isna()
                defense.loc[missing, "Abbreviation"] = defense.loc[missing, team_col].apply(_clean_team_abbr)

        for col in list(DEFENSE_POINTS_COLUMNS.values()) + list(DEFENSE_RANK_COLUMNS.values()):
            if col in defense.columns:
                defense[col] = pd.to_numeric(defense[col], errors="coerce")

    return players, schedule, defense


@st.cache_data
def load_schedule_year(year):
    path = REDZONE_SCHEDULE_FILES.get(int(year))
    if path is None or not path.exists():
        raise FileNotFoundError(f"Missing schedule for {year}: {path.name if path else year}")
    df = pd.read_excel(path, sheet_name=0)
    df.columns = df.columns.map(str).str.strip()
    df["Team"] = df["Team"].apply(_clean_team_abbr)
    df["Opp"] = df["Opp"].apply(_clean_team_abbr)
    df["Week"] = pd.to_numeric(df["Week"], errors="coerce")
    if "Home/Away" not in df.columns:
        df["Home/Away"] = ""
    df["Home/Away"] = df["Home/Away"].astype("string").str.title().str.strip()
    return df


def available_redzone_history_years():
    """Historical seasons available for player analysis.

    A season only requires the shared draft-data workbook plus its schedule.
    Defense files can be added independently and will improve matchup factors.
    """
    if not DATA.exists():
        return []
    return [
        y for y in [2023, 2024, 2025]
        if REDZONE_SCHEDULE_FILES[y].exists()
    ]


def player_games_for_year(player_name, year):
    players, schedule, defense = load_redzone_history_year(year)
    rows = players[players["Player"].astype("string").str.casefold() == str(player_name).casefold()]
    if rows.empty:
        return pd.DataFrame()

    player_row = rows.iloc[0]
    team = _clean_team_abbr(player_row.get("Team"))
    position = str(player_row.get("Position", "")).upper().strip()

    sched = schedule[
        (schedule["Team"] == team) & schedule["Week"].between(1, 18)
    ].copy().sort_values("Week")

    if sched.empty:
        return pd.DataFrame()

    scores = []
    for week in sched["Week"]:
        score = np.nan
        for candidate in [str(int(week)), int(week)]:
            if candidate in player_row.index:
                score = pd.to_numeric(player_row[candidate], errors="coerce")
                break
        scores.append(score)

    sched["Fantasy Pts"] = scores
    sched["Year"] = int(year)
    sched["Player"] = player_name
    sched["Position"] = position
    sched["Player Team"] = team
    sched["Is Bye"] = sched["Opp"].eq("BYE")
    return sched


def player_multiyear_games(player_name, years=None):
    years = years or available_redzone_history_years()
    frames = []
    for year in years:
        try:
            g = player_games_for_year(player_name, year)
            if not g.empty:
                frames.append(g)
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def weighted_player_baseline(player_name):
    """Weighted PPG using 50% 2025, 30% 2024, 20% 2023 when available."""
    pieces = []
    for year in available_redzone_history_years():
        try:
            players, _, _ = load_redzone_history_year(year)
        except Exception:
            continue
        rows = players[players["Player"].astype("string").str.casefold() == str(player_name).casefold()]
        if rows.empty:
            continue
        row = rows.iloc[0]
        avg = pd.to_numeric(row.get("AVG"), errors="coerce")
        if pd.isna(avg):
            games = player_games_for_year(player_name, year)
            games = games[~games["Is Bye"] & games["Fantasy Pts"].notna()]
            avg = games["Fantasy Pts"].mean() if not games.empty else np.nan
        if pd.notna(avg):
            pieces.append((year, float(avg), YEAR_WEIGHTS.get(year, 0)))

    if not pieces:
        return np.nan, pd.DataFrame()

    total_weight = sum(w for _, _, w in pieces)
    if total_weight <= 0:
        return np.nan, pd.DataFrame()

    baseline = sum(avg * w for _, avg, w in pieces) / total_weight
    detail = pd.DataFrame(pieces, columns=["Year", "PPG", "Weight"])
    detail["Normalized Weight"] = detail["Weight"] / total_weight
    return float(baseline), detail


def location_factors(player_name):
    """Return shrunk home/away multipliers from 2023-2025 actual games.

    Shrink small samples toward 1.00 so a few extreme games do not dominate.
    """
    games = player_multiyear_games(player_name)
    if games.empty:
        return {"Home": 1.0, "Away": 1.0}, pd.DataFrame()

    games = games[(~games["Is Bye"]) & games["Fantasy Pts"].notna()].copy()
    if games.empty:
        return {"Home": 1.0, "Away": 1.0}, pd.DataFrame()

    overall = games["Fantasy Pts"].mean()
    if pd.isna(overall) or overall <= 0:
        return {"Home": 1.0, "Away": 1.0}, pd.DataFrame()

    rows = []
    factors = {}
    for loc in ["Home", "Away"]:
        loc_games = games[games["Home/Away"].astype("string").str.casefold() == loc.casefold()]
        n = len(loc_games)
        avg = loc_games["Fantasy Pts"].mean() if n else overall
        raw = float(avg / overall) if overall else 1.0
        shrink = n / (n + 4.0)
        factor = 1.0 + (raw - 1.0) * shrink
        factor = float(np.clip(factor, 0.80, 1.20))
        factors[loc] = factor
        rows.append({
            "Location": loc,
            "Games": n,
            "Average": float(avg) if pd.notna(avg) else np.nan,
            "Raw Factor": raw,
            "Projection Factor": factor,
        })

    return factors, pd.DataFrame(rows)


def defense_factor_for_team(team, position):
    """Weighted 2023-2025 matchup multiplier.

    > 1.00 means the defense has historically allowed more fantasy production
    to that position (easier matchup). < 1.00 means tougher matchup.
    """
    team = _clean_team_abbr(team)
    position = str(position).upper().strip()
    pieces = []

    for year in available_redzone_history_years():
        try:
            _, _, defense = load_redzone_history_year(year)
        except Exception:
            continue
        if defense.empty or "Abbreviation" not in defense.columns:
            continue
        row = defense[defense["Abbreviation"] == team]
        if row.empty:
            continue

        points_col = DEFENSE_POINTS_COLUMNS.get(position)
        rank_col = DEFENSE_RANK_COLUMNS.get(position)
        factor = np.nan

        if points_col in defense.columns:
            league_avg = pd.to_numeric(defense[points_col], errors="coerce").mean()
            team_val = pd.to_numeric(row.iloc[0].get(points_col), errors="coerce")
            if pd.notna(team_val) and pd.notna(league_avg) and league_avg > 0:
                factor = float(team_val / league_avg)
        elif rank_col in defense.columns:
            rank = pd.to_numeric(row.iloc[0].get(rank_col), errors="coerce")
            if pd.notna(rank):
                # rank 1 = toughest, rank 32 = easiest
                factor = 0.85 + ((float(rank) - 1) / 31.0) * 0.30

        if pd.notna(factor):
            pieces.append((year, factor, YEAR_WEIGHTS.get(year, 0)))

    if not pieces:
        return 1.0, pd.DataFrame()

    total_weight = sum(w for _, _, w in pieces)
    factor = sum(f * w for _, f, w in pieces) / total_weight
    # Keep defensive adjustment meaningful but not overpowering.
    factor = float(np.clip(factor, 0.85, 1.15))
    detail = pd.DataFrame(pieces, columns=["Year", "Defense Factor", "Weight"])
    detail["Normalized Weight"] = detail["Weight"] / total_weight
    return factor, detail


def _find_2026_player_row(player_name):
    if "Player" not in adp26.columns:
        return None
    rows = adp26[adp26["Player"].astype(str).str.casefold() == str(player_name).casefold()]
    if rows.empty:
        return None
    return rows.iloc[0]


def _2026_team_position_role(player_name):
    """
    Estimate 2026 role from the player's ADP and same-team positional competition.

    This is deliberately much stricter for QB:
      - QB1 on team = starter-level role
      - QB2 = backup / spot-start role
      - QB3+ = emergency role

    RB/WR/TE use team order plus the ADP gap to the teammate ahead.
    The returned Opportunity Factor multiplies the historical/benchmark baseline.
    """
    player_row = _find_2026_player_row(player_name)
    if player_row is None:
        return {
            "Opportunity Factor": 0.0,
            "Team Role": "Not in 2026 ADP",
            "Team Position Rank": np.nan,
            "Starter Probability": 0.0,
            "Teammates": pd.DataFrame(),
        }

    team = _clean_team_abbr(player_row.get("Team"))
    position = str(player_row.get("Position", "")).upper().strip()
    overall_rank = pd.to_numeric(player_row.get("Rank"), errors="coerce")
    pos_rank = pd.to_numeric(player_row.get("Pos Rank"), errors="coerce")

    peers = adp26.copy()
    peers["_TeamClean"] = peers["Team"].map(_clean_team_abbr)
    peers["_PosClean"] = peers["Position"].astype(str).str.upper().str.strip()
    peers = peers[
        (peers["_TeamClean"] == team) &
        (peers["_PosClean"] == position)
    ].copy()

    peers["Rank"] = pd.to_numeric(peers["Rank"], errors="coerce")
    peers["Pos Rank"] = pd.to_numeric(peers["Pos Rank"], errors="coerce")
    peers = peers.sort_values(["Rank", "Pos Rank"], na_position="last").reset_index(drop=True)
    peers["Team Position Rank"] = np.arange(1, len(peers) + 1)

    selected = peers[peers["Player"].astype(str).str.casefold() == str(player_name).casefold()]
    if selected.empty:
        team_pos_rank = 99
    else:
        team_pos_rank = int(selected.iloc[0]["Team Position Rank"])

    leader_pos_rank = pd.to_numeric(peers.iloc[0]["Pos Rank"], errors="coerce") if not peers.empty else np.nan
    ahead = peers[peers["Team Position Rank"] < team_pos_rank].copy()
    nearest_ahead_pos_rank = (
        pd.to_numeric(ahead.iloc[-1]["Pos Rank"], errors="coerce")
        if not ahead.empty else np.nan
    )

    gap_to_leader = (
        float(pos_rank - leader_pos_rank)
        if pd.notna(pos_rank) and pd.notna(leader_pos_rank) else np.nan
    )
    gap_to_ahead = (
        float(pos_rank - nearest_ahead_pos_rank)
        if pd.notna(pos_rank) and pd.notna(nearest_ahead_pos_rank) else gap_to_leader
    )

    # Default role settings.
    factor = 1.0
    starter_prob = 1.0
    role = f"{position}{team_pos_rank} on team"

    if position == "QB":
        if team_pos_rank == 1:
            factor = 1.00
            starter_prob = 0.97
            role = "Projected starting QB"
        elif team_pos_rank == 2:
            factor = 0.12
            starter_prob = 0.10
            role = "Backup QB"
        else:
            factor = 0.04
            starter_prob = 0.03
            role = "Depth QB"

    elif position == "RB":
        if team_pos_rank == 1:
            # A very close RB2 signals a committee even for the nominal RB1.
            second = peers[peers["Team Position Rank"] == 2]
            second_gap = np.nan
            if not second.empty and pd.notna(pos_rank):
                second_pos_rank = pd.to_numeric(second.iloc[0]["Pos Rank"], errors="coerce")
                if pd.notna(second_pos_rank):
                    second_gap = float(second_pos_rank - pos_rank)
            if pd.notna(second_gap) and second_gap <= 10:
                factor, role = 0.90, "RB1 — strong committee"
            elif pd.notna(second_gap) and second_gap <= 25:
                factor, role = 0.96, "RB1 — shared backfield"
            else:
                factor, role = 1.00, "Clear RB1"
        elif team_pos_rank == 2:
            if pd.notna(gap_to_ahead) and gap_to_ahead <= 10:
                factor, role = 0.82, "RB2 — near-even committee"
            elif pd.notna(gap_to_ahead) and gap_to_ahead <= 25:
                factor, role = 0.68, "RB2 — meaningful committee role"
            else:
                factor, role = 0.48, "RB2 — clear backup/change-of-pace"
        elif team_pos_rank == 3:
            factor, role = 0.30, "RB3 — depth role"
        else:
            factor, role = 0.18, f"RB{team_pos_rank} — deep depth"

    elif position == "WR":
        if team_pos_rank == 1:
            factor, role = 1.00, "Team WR1"
        elif team_pos_rank == 2:
            factor, role = 0.95, "Team WR2"
        elif team_pos_rank == 3:
            factor, role = 0.82, "Team WR3"
        elif team_pos_rank == 4:
            factor, role = 0.58, "Team WR4"
        else:
            factor, role = 0.35, f"WR{team_pos_rank} — depth role"

    elif position == "TE":
        if team_pos_rank == 1:
            factor, role = 1.00, "Team TE1"
        elif team_pos_rank == 2:
            factor, role = 0.48, "Team TE2"
        else:
            factor, role = 0.25, f"TE{team_pos_rank} — depth role"

    # Very late ADP adds another signal that a player may not have a weekly fantasy role.
    # Keep this mild for skill positions because late players can still become relevant.
    if pd.notna(overall_rank):
        if position == "QB" and overall_rank >= 250 and team_pos_rank > 1:
            factor *= 0.75
        elif position in {"RB", "WR", "TE"} and overall_rank >= 350 and team_pos_rank > 1:
            factor *= 0.85

    factor = float(np.clip(factor, 0.0, 1.05))

    teammate_view = peers[["Player", "POS", "Rank", "Pos Rank", "Team Position Rank"]].copy()
    teammate_view = teammate_view.rename(columns={"Rank": "Overall ADP Rank"})

    return {
        "Opportunity Factor": factor,
        "Team Role": role,
        "Team Position Rank": team_pos_rank,
        "Starter Probability": starter_prob,
        "Overall ADP Rank": float(overall_rank) if pd.notna(overall_rank) else np.nan,
        "Positional ADP Rank": float(pos_rank) if pd.notna(pos_rank) else np.nan,
        "Gap To Leader": gap_to_leader,
        "Teammates": teammate_view,
    }


def projected_2026_schedule(player_name):
    player_row = _find_2026_player_row(player_name)
    if player_row is None:
        return pd.DataFrame(), {}

    position = str(player_row.get("Position", player_row.get("POS", ""))).upper().strip()
    team = _clean_team_abbr(player_row.get("Team"))
    if not team or not position:
        return pd.DataFrame(), {}

    schedule = load_schedule_year(2026)
    sched = schedule[
        (schedule["Team"] == team) & schedule["Week"].between(1, 18)
    ].copy().sort_values("Week")

    baseline, baseline_detail = weighted_player_baseline(player_name)
    loc_factors, loc_detail = location_factors(player_name)

    # If a player has no multi-year history (rookie/new player), fall back to
    # the 2026 expected PPG from the draft-value model when possible.
    if pd.isna(baseline):
        pos_rank = pd.to_numeric(player_row.get("Pos Rank", player_row.get("POS Rank")), errors="coerce")
        if pd.notna(pos_rank):
            baseline = finish_expected_ppg(position, int(pos_rank))

    if pd.isna(baseline):
        return pd.DataFrame(), {
            "Player": player_name,
            "Team": team,
            "Position": position,
            "Baseline": np.nan,
        }

    projected = []
    for _, row in sched.iterrows():
        opp = _clean_team_abbr(row.get("Opp"))
        location = str(row.get("Home/Away", "Home")).title().strip()
        is_bye = opp == "BYE"

        if is_bye:
            def_factor = 1.0
            loc_factor = 1.0
            points = 0.0
        else:
            loc_factor = loc_factors.get(location, 1.0)
            def_factor, _ = defense_factor_for_team(opp, position)
            points = float(baseline) * loc_factor * def_factor

        projected.append({
            "Week": int(row["Week"]),
            "Opponent": opp,
            "Home/Away": location,
            "Baseline PPG": float(baseline),
            "Location Factor": loc_factor,
            "Defense Factor": def_factor,
            "Projected Pts": round(points, 1),
        })

    result = pd.DataFrame(projected)
    meta = {
        "Player": player_name,
        "Team": team,
        "Position": position,
        "Baseline": float(baseline),
        "Home Factor": loc_factors.get("Home", 1.0),
        "Away Factor": loc_factors.get("Away", 1.0),
        "Opportunity Factor": opportunity_factor,
        "Role Profile": role_profile,
        "Baseline Detail": baseline_detail,
        "Location Detail": loc_detail,
    }
    return result, meta


def projected_defense_profile(team, position):
    """Weighted 2023-2025 defense-vs-position profile for a 2026 opponent."""
    team = _clean_team_abbr(team)
    position = str(position).upper().strip()
    rows = []

    for year in available_redzone_history_years():
        try:
            _, _, defense = load_redzone_history_year(year)
        except Exception:
            continue
        if defense.empty or "Abbreviation" not in defense.columns:
            continue

        match = defense[defense["Abbreviation"] == team]
        if match.empty:
            continue

        points_col = DEFENSE_POINTS_COLUMNS.get(position)
        rank_col = DEFENSE_RANK_COLUMNS.get(position)
        pts = pd.to_numeric(match.iloc[0].get(points_col), errors="coerce") if points_col in defense.columns else np.nan
        rank = pd.to_numeric(match.iloc[0].get(rank_col), errors="coerce") if rank_col in defense.columns else np.nan
        weight = YEAR_WEIGHTS.get(year, 0)
        rows.append({"Year": year, "Points Allowed": pts, "Rank": rank, "Weight": weight})

    detail = pd.DataFrame(rows)
    if detail.empty:
        return {"Points Allowed": np.nan, "Rank": np.nan, "Factor": 1.0}, detail

    def weighted(col):
        valid = detail[pd.to_numeric(detail[col], errors="coerce").notna()].copy()
        if valid.empty:
            return np.nan
        denom = valid["Weight"].sum()
        if denom <= 0:
            return np.nan
        return float((pd.to_numeric(valid[col], errors="coerce") * valid["Weight"]).sum() / denom)

    pts = weighted("Points Allowed")
    rank = weighted("Rank")
    factor, _ = defense_factor_for_team(team, position)
    return {"Points Allowed": pts, "Rank": rank, "Factor": factor}, detail


def player_profile_history(player_name):
    """Blended 2023-2025 player profile used behind the 2026 projection."""
    games = player_multiyear_games(player_name)
    if games.empty:
        return {}, pd.DataFrame(), pd.DataFrame()

    actual = games[(~games["Is Bye"]) & games["Fantasy Pts"].notna()].copy()
    if actual.empty:
        return {}, pd.DataFrame(), pd.DataFrame()

    actual["Fantasy Pts"] = pd.to_numeric(actual["Fantasy Pts"], errors="coerce")
    actual = actual[actual["Fantasy Pts"].notna()].copy()

    home = actual[actual["Home/Away"].astype("string").str.casefold() == "home"]
    away = actual[actual["Home/Away"].astype("string").str.casefold() == "away"]

    thresholds = [10, 15, 20, 25, 30]
    boom_rows = []
    for t in thresholds:
        hits = int((actual["Fantasy Pts"] >= t).sum())
        games_n = len(actual)
        boom_rows.append({
            "Threshold": f"{t}+ Points",
            "Games": hits,
            "Boom %": (hits / games_n * 100.0) if games_n else np.nan,
        })

    by_year = (
        actual.groupby("Year", as_index=False)
        .agg(Games=("Fantasy Pts", "count"), PPG=("Fantasy Pts", "mean"), Total=("Fantasy Pts", "sum"))
        .sort_values("Year")
    )

    baseline, _ = weighted_player_baseline(player_name)
    summary = {
        "Games": len(actual),
        "Average PPG": float(actual["Fantasy Pts"].mean()),
        "Weighted Baseline": baseline,
        "Home PPG": float(home["Fantasy Pts"].mean()) if not home.empty else np.nan,
        "Road PPG": float(away["Fantasy Pts"].mean()) if not away.empty else np.nan,
        "Median": float(actual["Fantasy Pts"].median()),
        "Std Dev": float(actual["Fantasy Pts"].std(ddof=0)) if len(actual) > 1 else 0.0,
    }
    return summary, pd.DataFrame(boom_rows), by_year


def color_projected_defense_rank(value):
    if pd.isna(value):
        return ""
    try:
        rank = float(value)
    except (TypeError, ValueError):
        return ""
    # Rank 1 = toughest; rank 32 = easiest.
    if rank >= 25:
        return "background-color: #b7e1cd; color: #0b4128;"
    if rank >= 17:
        return "background-color: #d9ead3; color: #274e13;"
    if rank >= 9:
        return "background-color: #fff2cc; color: #7f6000;"
    return "background-color: #f4cccc; color: #660000;"


def projected_2026_schedule(player_name):
    player_row = _find_2026_player_row(player_name)
    if player_row is None:
        return pd.DataFrame(), {}

    position = str(player_row.get("Position", player_row.get("POS", ""))).upper().strip()
    team = _clean_team_abbr(player_row.get("Team"))
    if not team or not position:
        return pd.DataFrame(), {}

    schedule = load_schedule_year(2026)
    sched = schedule[
        (schedule["Team"] == team) & schedule["Week"].between(1, 18)
    ].copy().sort_values("Week")

    baseline, baseline_detail = weighted_player_baseline(player_name)
    loc_factors, loc_detail = location_factors(player_name)

    role_profile = _2026_team_position_role(player_name)
    opportunity_factor = float(
        role_profile.get("Opportunity Factor", 1.0)
    )
    role_profile = _2026_team_position_role(player_name)
    opportunity_factor = role_profile.get("Opportunity Factor", 1.0)

    # Rookie / no-history fallback from the existing draft-value model.
    if pd.isna(baseline):
        pos_rank = pd.to_numeric(player_row.get("Pos Rank", player_row.get("POS Rank")), errors="coerce")
        if pd.notna(pos_rank):
            baseline = finish_expected_ppg(position, int(pos_rank))

    if pd.isna(baseline):
        return pd.DataFrame(), {
            "Player": player_name, "Team": team, "Position": position, "Baseline": np.nan,
        }

    projected = []
    for _, row in sched.iterrows():
        opp = _clean_team_abbr(row.get("Opp"))
        location = str(row.get("Home/Away", "Home")).title().strip()
        is_bye = opp == "BYE"

        if is_bye:
            def_profile = {"Points Allowed": np.nan, "Rank": np.nan, "Factor": 1.0}
            loc_factor = 1.0
            points = 0.0
        else:
            loc_factor = loc_factors.get(location, 1.0)
            def_profile, _ = projected_defense_profile(opp, position)
            points = (
                float(baseline)
                * opportunity_factor
                * loc_factor
                * def_profile["Factor"]
            )

        projected.append({
            "Week": int(row["Week"]),
            "Opponent": opp,
            "Home/Away": location,
            "Historical Baseline": float(baseline),
            "Opportunity Factor": opportunity_factor,
            "2026 DEF Rank": def_profile["Rank"],
            "Historical Pts Allowed": def_profile["Points Allowed"],
            "Location Factor": loc_factor,
            "Defense Factor": def_profile["Factor"],
            "Projected Pts": round(points, 1),
        })

    result = pd.DataFrame(projected)
    meta = {
        "Player": player_name,
        "Team": team,
        "Position": position,
        "Baseline": float(baseline),
        "Home Factor": loc_factors.get("Home", 1.0),
        "Away Factor": loc_factors.get("Away", 1.0),
        "Opportunity Factor": opportunity_factor,
        "Role Profile": role_profile,
        "Baseline Detail": baseline_detail,
        "Location Detail": loc_detail,
    }
    return result, meta


def render_redzone_multiyear_tab():
    st.header("🏟️ RedZone Analytics — 2026 Player Profile")
    st.caption(
        "One 2026 player profile powered by 2023–2025 history: scoring average, home/road splits, "
        "boom rates, opponent strength and a week-by-week 2026 projection."
    )

    if 2026 not in REDZONE_SCHEDULE_FILES or not REDZONE_SCHEDULE_FILES[2026].exists():
        st.error("2026_NFL_Schedules.xlsx is missing.")
        return
    if "Player" not in adp26.columns:
        st.error("The 2026 ADP sheet needs a Player column.")
        return

    projection_pool = adp26.copy()
    pos_col = "Position" if "Position" in projection_pool.columns else "POS" if "POS" in projection_pool.columns else None
    team_col = "Team" if "Team" in projection_pool.columns else None

    f1, f2, f3 = st.columns(3)
    if pos_col:
        positions = sorted(projection_pool[pos_col].dropna().astype(str).str.upper().unique())
        chosen_positions = f1.multiselect("Position", positions, default=positions, key="rz26_positions")
        projection_pool = projection_pool[projection_pool[pos_col].astype(str).str.upper().isin(chosen_positions)]
    if team_col:
        teams = sorted(projection_pool[team_col].dropna().astype(str).str.upper().unique())
        chosen_teams = f2.multiselect("Team", teams, default=teams, key="rz26_teams")
        projection_pool = projection_pool[projection_pool[team_col].astype(str).str.upper().isin(chosen_teams)]

    player_names = projection_pool["Player"].dropna().astype(str).tolist()
    if not player_names:
        st.warning("No players match those filters.")
        return

    selected_player = f3.selectbox("Player", player_names, key="rz26_player")
    projection, meta = projected_2026_schedule(selected_player)
    history, boom_df, by_year = player_profile_history(selected_player)

    if projection.empty:
        st.warning(
            "I could not build this player's 2026 projection. Check the player's 2026 team/position and historical data."
        )
        return

    non_bye = projection[projection["Opponent"] != "BYE"].copy()
    home_proj = non_bye[non_bye["Home/Away"].astype("string").str.casefold() == "home"]
    away_proj = non_bye[non_bye["Home/Away"].astype("string").str.casefold() == "away"]

    # ---------------- Historical profile ----------------
    st.subheader(f"{selected_player} — Historical Profile")
    h1, h2, h3, h4, h5 = st.columns(5)
    hist_avg = history.get("Average PPG", np.nan)
    hist_home = history.get("Home PPG", np.nan)
    hist_away = history.get("Road PPG", np.nan)
    weighted = history.get("Weighted Baseline", meta.get("Baseline", np.nan))
    games_n = history.get("Games", 0)
    h1.metric("2023–25 Avg PPG", f"{hist_avg:.1f}" if pd.notna(hist_avg) else "—")
    h2.metric("Weighted PPG", f"{weighted:.1f}" if pd.notna(weighted) else "—")
    h3.metric("🏠 Home PPG", f"{hist_home:.1f}" if pd.notna(hist_home) else "—")
    h4.metric("✈️ Road PPG", f"{hist_away:.1f}" if pd.notna(hist_away) else "—")
    h5.metric("Historical Games", f"{games_n}")

    if not boom_df.empty:
        st.markdown("#### Boom Rate")
        boom_cols = st.columns(len(boom_df))
        for col, (_, row) in zip(boom_cols, boom_df.iterrows()):
            col.metric(row["Threshold"], f"{row['Boom %']:.1f}%")
            col.caption(f"{int(row['Games'])} historical games")

    # ---------------- 2026 headline projection ----------------
    st.subheader("2026 Projection")
    easiest = non_bye.sort_values("Projected Pts", ascending=False).head(1)
    toughest = non_bye.sort_values("Projected Pts", ascending=True).head(1)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Projected Season Points", f"{non_bye['Projected Pts'].sum():.1f}")
    m2.metric("Projected PPG", f"{non_bye['Projected Pts'].mean():.1f}")
    m3.metric("Projected Home PPG", f"{home_proj['Projected Pts'].mean():.1f}" if not home_proj.empty else "—")
    m4.metric("Projected Road PPG", f"{away_proj['Projected Pts'].mean():.1f}" if not away_proj.empty else "—")

    role_profile = meta.get("Role Profile", {})
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("2026 Team Role", role_profile.get("Team Role", "—"))
    r2.metric(
        "Opportunity Factor",
        f"{meta.get('Opportunity Factor', 1.0):.0%}"
    )
    r3.metric(
        "Overall ADP",
        f"#{int(role_profile['Overall ADP Rank'])}"
        if pd.notna(role_profile.get("Overall ADP Rank")) else "—"
    )
    r4.metric(
        "Position ADP",
        f"{meta.get('Position','')}{int(role_profile['Positional ADP Rank'])}"
        if pd.notna(role_profile.get("Positional ADP Rank")) else "—"
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Historical Baseline", f"{meta.get('Baseline', np.nan):.1f} PPG")
    if not easiest.empty:
        er = easiest.iloc[0]
        c2.metric("Best 2026 Matchup", f"Wk {int(er['Week'])} vs {er['Opponent']}")
        c2.caption(f"{er['Projected Pts']:.1f} projected points")
    if not toughest.empty:
        tr = toughest.iloc[0]
        c3.metric("Toughest 2026 Matchup", f"Wk {int(tr['Week'])} vs {tr['Opponent']}")
        c3.caption(f"{tr['Projected Pts']:.1f} projected points")

    # ---------------- Heat-map matchup table ----------------
    st.subheader("2026 Weekly Matchup Heat Map")
    heat = projection.copy()
    heat["Role / Opportunity %"] = (heat["Opportunity Factor"] * 100).round(1)
    heat["Home/Road Adj %"] = ((heat["Location Factor"] - 1) * 100).round(1)
    heat["Defense Adj %"] = ((heat["Defense Factor"] - 1) * 100).round(1)
    heat = heat[[
        "Week", "Opponent", "Home/Away", "2026 DEF Rank",
        "Historical Pts Allowed", "Role / Opportunity %",
        "Home/Road Adj %", "Defense Adj %", "Projected Pts"
    ]]

    styled = (
        heat.style
        .map(color_projected_defense_rank, subset=["2026 DEF Rank"])
        .background_gradient(cmap="RdYlGn", subset=["Projected Pts"])
        .format({
            "2026 DEF Rank": "{:.1f}",
            "Historical Pts Allowed": "{:.1f}",
            "Role / Opportunity %": "{:.1f}%",
            "Home/Road Adj %": "{:+.1f}%",
            "Defense Adj %": "{:+.1f}%",
            "Projected Pts": "{:.1f}",
        }, na_rep="—")
    )
    st.dataframe(styled, use_container_width=True, hide_index=True, height=650)
    st.caption("Defense rank: red = tougher, green = easier. Projected-points shading runs low-to-high from red to green.")

    # ---------------- Charts ----------------
    st.subheader("2026 Projected Points by Week")
    fig = px.bar(
        non_bye,
        x="Week",
        y="Projected Pts",
        color="Projected Pts",
        color_continuous_scale="RdYlGn",
        hover_data=["Opponent", "Home/Away", "2026 DEF Rank", "Historical Pts Allowed"],
        title=f"{selected_player} — 2026 Weekly Projection",
        text="Projected Pts",
    )
    fig.update_traces(texttemplate="%{text:.1f}", textposition="outside")
    fig.update_xaxes(dtick=1)
    fig.update_layout(coloraxis_showscale=False, height=520)
    st.plotly_chart(fig, use_container_width=True)

    teammates = role_profile.get("Teammates")
    if isinstance(teammates, pd.DataFrame) and not teammates.empty:
        with st.expander("2026 same-team positional competition"):
            st.caption(
                "Players are ordered by 2026 ADP. This is the role/depth signal used to keep backups "
                "and committee players from receiving starter-level projections."
            )
            st.dataframe(teammates, hide_index=True, use_container_width=True)

    if not by_year.empty:
        with st.expander("Historical averages used in this profile"):
            st.dataframe(by_year.round(1), hide_index=True, use_container_width=True)
            baseline_detail = meta.get("Baseline Detail")
            if isinstance(baseline_detail, pd.DataFrame) and not baseline_detail.empty:
                st.write("Recency weighting")
                st.dataframe(baseline_detail.round(3), hide_index=True, use_container_width=True)
            loc_detail = meta.get("Location Detail")
            if isinstance(loc_detail, pd.DataFrame) and not loc_detail.empty:
                st.write("Home / road history")
                st.dataframe(loc_detail.round(3), hide_index=True, use_container_width=True)



    st.markdown("---")
    st.subheader("🗓️ 2026 Schedule & Weekly Projection")
    st.caption(
        "Green = easier matchup, yellow = neutral, red = tougher. "
        "Projected points include role/opportunity, home/road, and defense adjustments."
    )

    schedule_view = projection.copy()

    if not schedule_view.empty:
        schedule_view["Matchup Rating"] = schedule_view["2026 DEF Rank"].apply(
            lambda x:
                "🟢 Easy" if pd.notna(x) and float(x) >= 24
                else "🟡 Neutral" if pd.notna(x) and float(x) >= 10
                else "🔴 Tough" if pd.notna(x)
                else "—"
        )

        schedule_display = schedule_view[[
            "Week",
            "Opponent",
            "Home/Away",
            "2026 DEF Rank",
            "Matchup Rating",
            "Projected Pts",
        ]].copy()

        def _color_def_rank(v):
            try:
                v = float(v)
            except Exception:
                return ""
            if v >= 24:
                return "background-color: #d9ead3; color: #274e13;"
            if v >= 10:
                return "background-color: #fff2cc; color: #7f6000;"
            return "background-color: #f4cccc; color: #660000;"

        def _color_projected(v):
            try:
                v = float(v)
            except Exception:
                return ""
            col = schedule_display["Projected Pts"].dropna()
            if col.empty:
                return ""
            lo = float(col.quantile(0.33))
            hi = float(col.quantile(0.67))
            if v >= hi:
                return "background-color: #d9ead3; color: #274e13;"
            if v >= lo:
                return "background-color: #fff2cc; color: #7f6000;"
            return "background-color: #f4cccc; color: #660000;"

        styled_schedule = (
            schedule_display.style
            .format({
                "2026 DEF Rank": "{:.0f}",
                "Projected Pts": "{:.1f}",
            })
            .map(_color_def_rank, subset=["2026 DEF Rank"])
            .map(_color_projected, subset=["Projected Pts"])
        )

        st.dataframe(
            styled_schedule,
            use_container_width=True,
            hide_index=True,
            height=650,
        )

        non_bye = schedule_view[
            schedule_view["Opponent"].astype(str).str.upper() != "BYE"
        ].copy()

        if not non_bye.empty:
            easiest_row = non_bye.sort_values(
                ["2026 DEF Rank", "Projected Pts"],
                ascending=[False, False]
            ).iloc[0]

            toughest_row = non_bye.sort_values(
                ["2026 DEF Rank", "Projected Pts"],
                ascending=[True, True]
            ).iloc[0]

            s1, s2, s3 = st.columns(3)
            s1.metric("Projected 2026 PPG", f"{non_bye['Projected Pts'].mean():.1f}")
            s2.metric(
                "Easiest Matchup",
                f"Wk {int(easiest_row['Week'])} vs {easiest_row['Opponent']}"
            )
            s3.metric(
                "Toughest Matchup",
                f"Wk {int(toughest_row['Week'])} vs {toughest_row['Opponent']}"
            )

    with st.expander("How the 2026 projection works"):
        st.markdown(
            """
**Weekly projection = weighted player PPG × 2026 opportunity/role factor × home/road adjustment × opponent-defense adjustment**

The **2026 opportunity/role factor** uses the player's overall ADP, positional ADP, and the ADPs of teammates at the same position. This prevents backups from being treated like starters. For example, a team's QB2 receives only a small expected-playing-time factor, while the team's QB1 receives the starter-level projection.

- Historical player baseline weights **2025 at 50%, 2024 at 30%, 2023 at 20%**.
- Boom percentages use every available 2023–2025 played game.
- Home/road adjustment comes from the player's own historical split and is shrunk toward neutral when the sample is small.
- Opponent strength combines that defense's 2023–2025 fantasy points allowed to the player's position using the same 50/30/20 recency weights.
- **Defense Rank 1 = toughest; 32 = easiest.**
- Defense adjustments are capped at ±15% and location adjustments at ±20% to prevent noisy splits from dominating.
- For rookies or players without NFL history, the app falls back to the existing positional projection benchmark when available.
            """
        )

    csv_data = projection.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download 2026 Player Projection",
        data=csv_data,
        file_name=f"{selected_player.replace(' ', '_').replace(chr(39), '')}_2026_projection.csv",
        mime="text/csv",
        key="rz26_download",
    )




def render_weekly_matchup_tab():
    st.header("🔥 2026 Weekly Matchups & Player Compare")
    st.caption(
        "Choose a week to rank the best and worst fantasy matchups, then compare similar players side-by-side."
    )

    # =========================================================
    # WEEKLY MATCHUP FINDER
    # =========================================================

    fc1, fc2, fc3 = st.columns([1, 1, 2])
    finder_week = fc1.selectbox(
        "Week",
        list(range(1, 19)),
        key="rz_matchup_finder_week",
    )
    finder_position = fc2.selectbox(
        "Position",
        ["All", "QB", "RB", "WR", "TE"],
        key="rz_matchup_finder_position",
    )
    min_opportunity = fc3.slider(
        "Minimum opportunity factor",
        0, 100, 35, 5,
        key="rz_matchup_min_opportunity",
        help="Increase this to remove backups and deep depth players.",
    ) / 100.0

    @st.cache_data(show_spinner=False)
    def _weekly_matchup_board(week):
        rows = []

        schedule = load_schedule_year(2026)

        if "Player" not in adp26.columns:
            return pd.DataFrame()

        for _, player_row in adp26.iterrows():
            player = str(player_row.get("Player", "")).strip()
            if not player:
                continue

            position = str(
                player_row.get(
                    "Position",
                    player_row.get("POS", "")
                )
            ).upper().strip()

            team = _clean_team_abbr(
                player_row.get("Team")
            )

            if not team or not position:
                continue

            game_rows = schedule[
                (schedule["Team"] == team)
                & (schedule["Week"] == int(week))
            ]

            if game_rows.empty:
                continue

            game = game_rows.iloc[0]

            opponent = _clean_team_abbr(
                game.get("Opp")
            )

            if opponent == "BYE":
                continue

            location = str(
                game.get("Home/Away", "Home")
            ).title().strip()

            baseline, _ = weighted_player_baseline(
                player
            )

            # Rookie / no-history fallback.
            if pd.isna(baseline):
                pos_rank = pd.to_numeric(
                    player_row.get(
                        "Pos Rank",
                        player_row.get("POS Rank")
                    ),
                    errors="coerce"
                )

                if pd.notna(pos_rank):
                    baseline = finish_expected_ppg(
                        position,
                        int(pos_rank)
                    )

            if pd.isna(baseline):
                continue

            role_profile = _2026_team_position_role(
                player
            )

            opportunity = float(
                role_profile.get(
                    "Opportunity Factor",
                    1.0
                )
            )

            loc_factors, _ = location_factors(
                player
            )

            location_factor = loc_factors.get(
                location,
                1.0
            )

            defense_profile, _ = projected_defense_profile(
                opponent,
                position
            )

            defense_factor = float(
                defense_profile.get(
                    "Factor",
                    1.0
                )
            )

            defense_rank = pd.to_numeric(
                defense_profile.get(
                    "Rank",
                    np.nan
                ),
                errors="coerce"
            )

            projected_points = (
                float(baseline)
                * opportunity
                * location_factor
                * defense_factor
            )

            rows.append({
                "Player": player,
                "Position": position,
                "Team": team,
                "Role": role_profile.get(
                    "Team Role",
                    ""
                ),
                "Opportunity %": opportunity * 100,
                "Overall ADP": role_profile.get(
                    "Overall ADP Rank",
                    np.nan
                ),
                "Pos ADP": role_profile.get(
                    "Positional ADP Rank",
                    np.nan
                ),
                "Opponent": opponent,
                "Home/Away": location,
                "DEF Rank": defense_rank,
                "Historical PPG": float(baseline),
                "Defense Adj %": (defense_factor - 1) * 100,
                "Home/Road Adj %": (location_factor - 1) * 100,
                "Projected Pts": round(projected_points, 1),
            })

        board = pd.DataFrame(rows)

        if board.empty:
            return board

        board["Weekly Rank"] = (
            board["Projected Pts"]
            .rank(
                method="min",
                ascending=False
            )
            .astype("Int64")
        )

        board["Matchup Score"] = (
            board["Projected Pts"].rank(pct=True) * 70
            + board["DEF Rank"].fillna(16.5).rank(pct=True) * 20
            + (board["Opportunity %"] / 100.0).clip(0, 1) * 10
        )

        return board.sort_values(
            ["Projected Pts", "Matchup Score"],
            ascending=[False, False]
        ).reset_index(drop=True)


    weekly_board = _weekly_matchup_board(finder_week)

    if not weekly_board.empty:
        st.caption(
            f"{len(weekly_board)} players have a Week {finder_week} projection before filters."
        )

    if weekly_board.empty:
        st.info("No projections are available for that week.")
    else:
        filtered_board = weekly_board.copy()

        if finder_position != "All":
            filtered_board = filtered_board[
                filtered_board["Position"] == finder_position
            ].copy()

        filtered_board = filtered_board[
            filtered_board["Opportunity %"] >= min_opportunity * 100
        ].copy()

        if filtered_board.empty:
            st.warning("No players meet those filters.")
        else:
            matchup_only = filtered_board.copy()

            matchup_only["Home Bonus"] = (
                matchup_only["Home/Away"]
                .map({"Home": 1.0, "Away": -1.0})
                .fillna(0.0)
            )

            matchup_only["Matchup Ease Score"] = (
                pd.to_numeric(
                    matchup_only["DEF Rank"], errors="coerce"
                ).fillna(16.5) * 2.2
                + pd.to_numeric(
                    matchup_only["Defense Adj %"], errors="coerce"
                ).fillna(0.0) * 1.2
                + matchup_only["Home Bonus"] * 3.0
            )

            matchup_only["Matchup Rank"] = (
                matchup_only["Matchup Ease Score"]
                .rank(method="min", ascending=False)
                .astype("Int64")
            )

            easiest_matchups = matchup_only.sort_values(
                ["Matchup Ease Score", "Projected Pts"],
                ascending=[False, False]
            ).head(12)

            hardest_matchups = matchup_only.sort_values(
                ["Matchup Ease Score", "Projected Pts"],
                ascending=[True, True]
            ).head(12)

            st.subheader("🗓️ Easiest & Toughest Schedules This Week")
            st.caption(
                "This ranks the matchup itself, not the player's talent. "
                "A lower-tier player can have an easier matchup than a star."
            )

            m1, m2 = st.columns(2)

            matchup_cols = [
                "Matchup Rank",
                "Player",
                "Position",
                "Opponent",
                "Home/Away",
                "DEF Rank",
                "Defense Adj %",
                "Projected Pts",
            ]

            with m1:
                st.markdown("**🟢 Easiest Matchups**")
                st.dataframe(
                    easiest_matchups[matchup_cols].style.format({
                        "DEF Rank": "{:.0f}",
                        "Defense Adj %": "{:+.1f}%",
                        "Projected Pts": "{:.1f}",
                    }),
                    hide_index=True,
                    use_container_width=True,
                )

            with m2:
                st.markdown("**🔴 Toughest Matchups**")
                st.dataframe(
                    hardest_matchups[matchup_cols].style.format({
                        "DEF Rank": "{:.0f}",
                        "Defense Adj %": "{:+.1f}%",
                        "Projected Pts": "{:.1f}",
                    }),
                    hide_index=True,
                    use_container_width=True,
                )

            display_cols = [
                "Weekly Rank", "Player", "Position", "Opponent",
                "Home/Away", "DEF Rank", "Projected Pts",
                "Opportunity %"
            ]

            left, right = st.columns(2)
            with left:
                st.subheader("🟢 Best Matchups")
                st.dataframe(
                    filtered_board.head(10)[display_cols].style.format({
                        "DEF Rank": "{:.0f}",
                        "Projected Pts": "{:.1f}",
                        "Opportunity %": "{:.0f}%",
                    }),
                    hide_index=True,
                    use_container_width=True,
                )

            with right:
                st.subheader("🔴 Worst Matchups")
                st.dataframe(
                    filtered_board.sort_values(
                        ["Projected Pts", "Matchup Score"],
                        ascending=[True, True],
                    ).head(10)[display_cols].style.format({
                        "DEF Rank": "{:.0f}",
                        "Projected Pts": "{:.1f}",
                        "Opportunity %": "{:.0f}%",
                    }),
                    hide_index=True,
                    use_container_width=True,
                )

            st.subheader("Full Weekly Board")
            board_cols = [
                "Weekly Rank", "Player", "Position", "Team", "Role",
                "Opponent", "Home/Away", "DEF Rank", "Projected Pts",
                "Historical PPG", "Defense Adj %", "Home/Road Adj %",
                "Opportunity %",
                "Overall ADP", "Pos ADP"
            ]

            st.dataframe(
                filtered_board[board_cols].style.format({
                    "DEF Rank": "{:.0f}",
                    "Projected Pts": "{:.1f}",
                    "Historical PPG": "{:.1f}",
                    "Defense Adj %": "{:+.1f}%",
                    "Home/Road Adj %": "{:+.1f}%",
                    "Opportunity %": "{:.0f}%",
                    "Overall ADP": "{:.0f}",
                    "Pos ADP": "{:.0f}",
                }),
                hide_index=True,
                use_container_width=True,
                height=600,
            )

            # =====================================================
            # SIMILAR PLAYER COMPARISON
            # =====================================================
            st.markdown("---")
            st.header("⚖️ Compare Similar Players")
            st.caption(
                "Compare players at the same position for the selected week, "
                "or use the similar-ADP finder to locate the closest alternatives."
            )

            compare_positions = ["QB", "RB", "WR", "TE"]
            default_pos = (
                compare_positions.index(finder_position)
                if finder_position in compare_positions
                else 2
            )
            compare_pos = st.selectbox(
                "Compare position",
                compare_positions,
                index=default_pos,
                key="rz_compare_position",
            )

            compare_pool = weekly_board[
                weekly_board["Position"] == compare_pos
            ].copy()

            compare_names = compare_pool["Player"].tolist()

            if compare_names:
                selected_compare = st.multiselect(
                    "Players to compare",
                    compare_names,
                    default=compare_names[:2],
                    max_selections=5,
                    key="rz_compare_players",
                )

                if selected_compare:
                    comp = compare_pool[
                        compare_pool["Player"].isin(selected_compare)
                    ].copy()

                    comp_cols = [
                        "Player", "Role", "Opponent", "Home/Away",
                        "Projected Pts", "DEF Rank", "Historical PPG",
                        "Opportunity %",
                        "Overall ADP", "Pos ADP"
                    ]

                    st.dataframe(
                        comp[comp_cols].style.format({
                            "Projected Pts": "{:.1f}",
                            "DEF Rank": "{:.0f}",
                            "Historical PPG": "{:.1f}",
                            "Opportunity %": "{:.0f}%",
                                                    "Overall ADP": "{:.0f}",
                            "Pos ADP": "{:.0f}",
                        }),
                        hide_index=True,
                        use_container_width=True,
                    )

                    winner = comp.sort_values(
                        ["Projected Pts", "Matchup Score"],
                        ascending=False,
                    ).iloc[0]

                    st.success(
                        f"Best Week {finder_week} option: "
                        f"**{winner['Player']}** — "
                        f"{winner['Projected Pts']:.1f} projected points "
                        f"vs {winner['Opponent']} "
                        f"(DEF rank {winner['DEF Rank']:.0f})."
                    )

                    st.bar_chart(
                        comp.set_index("Player")[["Projected Pts"]]
                    )

                st.subheader("Find Similar ADP Players")
                anchor_player = st.selectbox(
                    "Anchor player",
                    compare_names,
                    key="rz_anchor_player",
                )

                anchor_row = compare_pool[
                    compare_pool["Player"] == anchor_player
                ].iloc[0]
                anchor_pos_adp = pd.to_numeric(
                    anchor_row["Pos ADP"], errors="coerce"
                )

                if pd.notna(anchor_pos_adp):
                    similar = compare_pool.copy()
                    similar["ADP Distance"] = (
                        pd.to_numeric(
                            similar["Pos ADP"], errors="coerce"
                        ) - anchor_pos_adp
                    ).abs()

                    similar = similar[
                        similar["Player"] != anchor_player
                    ].sort_values(
                        ["ADP Distance", "Projected Pts"],
                        ascending=[True, False],
                    ).head(8)

                    st.dataframe(
                        similar[[
                            "Player", "Pos ADP", "Opponent",
                            "DEF Rank", "Projected Pts",
                            "Opportunity %",
                            "ADP Distance"
                        ]].style.format({
                            "Pos ADP": "{:.0f}",
                            "DEF Rank": "{:.0f}",
                            "Projected Pts": "{:.1f}",
                            "Opportunity %": "{:.0f}%",
                                    "ADP Distance": "{:.0f}",
                        }),
                        hide_index=True,
                        use_container_width=True,
                    )



# ============================================================
# UI
# ============================================================
st.title("🏈 DraftKings Best Ball Optimizer")
st.caption(
    "Uses your 2026 rankings for availability and your 2022–2025 results for historical "
    "production, draft value and spike-week upside."
)

tab0, tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "🎯 2026 Round Decision",
    "🧠 Draft Plan",
    "⏱️ On the Clock",
    "📈 Player Value History",
    "🧪 Rookie Analysis",
    "📘 How It Works",
    "🏟️ RedZone Player Profile",
    "🔥 Weekly Matchups & Compare"
])


# ------------------------------------------------------------
# TAB 0 — 2026 ROUND DECISION
# ------------------------------------------------------------
with tab0:
    st.header("2026 Round Decision")
    st.write(
        "Choose the round you are entering. The page estimates which positional tier "
        "is available now, what should be available if you wait, and how historical "
        "value + boom-point values compare."
    )

    r1, r2, r3 = st.columns(3)
    market_rounds = sorted(market["Round"].unique())
    decision_round = r1.selectbox(
        "I am entering Round:",
        market_rounds,
        index=min(3, len(market_rounds)-1),
        key="decision_round"
    )
    boom_threshold = r2.selectbox(
        "Boom game threshold to emphasize",
        [10,15,20,25,30],
        index=2,
        format_func=lambda x: f"{x}+ point games"
    )
    min_boom_games = r3.slider(
        "Minimum average boom games",
        min_value=0.0,
        max_value=8.0,
        value=0.0,
        step=0.5,
        help="Example: 3.0 with 25+ selected means the historical group averaged at least three 25+ point games."
    )

    boom_col = boom_metric_for_threshold(boom_threshold)

    with st.expander("What do Boom 10 / 15 / 20 / 25 / 30 mean?", expanded=False):
        st.markdown("""
These are **counts of spike games**.

- **Boom 10 = number of games with 10+ fantasy points**
- **Boom 15 = number of games with 15+ fantasy points**
- **Boom 20 = number of games with 20+ fantasy points**
- **Boom 25 = number of games with 25+ fantasy points**
- **Boom 30 = number of games with 30+ fantasy points**

So if the Round 4 QB card says:

**25+ point games: 3.0**

that means historical Round 4 QBs averaged **3 games per season scoring at least 25 fantasy points**.

This is especially useful in Best Ball because those spike games can crack your optimal weekly lineup even when a player's normal weeks do not.

The **Minimum average boom games** control lets you require a certain amount of upside.

Example:

**25+ point games + minimum 3.0**

means only consider positions whose historical players averaged at least **three 25+ point games**.
""")

    boom_summary = round_position_boom_summary(decision_round)

    rows = []
    for pos in ["QB","RB","WR","TE"]:
        now_rank = available_entering_round(decision_round, pos)
        next_rank = available_next_round(decision_round, pos)
        now_ppg = finish_expected_ppg(pos, now_rank)
        next_ppg = finish_expected_ppg(pos, next_rank)

        b = boom_summary[boom_summary["Position"] == pos]
        if not b.empty:
            b = b.iloc[0]
            boom_rate = b.get(boom_col, np.nan)
            worth = b.get("Worth-It %", np.nan)
            avg_value = b.get("Avg Value %", np.nan)
            sample = b.get("Players", 0)
        else:
            boom_rate, worth, avg_value, sample = np.nan, np.nan, np.nan, 0

        wait_cost = now_ppg - next_ppg if pd.notna(now_ppg) and pd.notna(next_ppg) else np.nan

        rows.append({
            "Position": pos,
            "Available Now": f"{pos}{int(now_rank)}" if pd.notna(now_rank) else "N/A",
            "Expected PPG": now_ppg,
            "If You Wait": f"{pos}{int(next_rank)}" if pd.notna(next_rank) else "N/A",
            "Next Expected PPG": next_ppg,
            "PPG Cost of Waiting": wait_cost,
            boom_col: boom_rate,
            "Worth-It %": worth,
            "Avg Value %": avg_value,
            "Sample": sample
        })

    decision = pd.DataFrame(rows)

    # Score components normalized within the four positions
    decision["PPG Score"] = minmax(decision["Expected PPG"])
    decision["Worth Score"] = decision["Worth-It %"].fillna(50).clip(0,100)
    decision["Value Score"] = minmax(decision["Avg Value %"].fillna(100))
    decision["Boom Score"] = minmax(decision[boom_col].fillna(0))
    decision["Urgency Score"] = minmax(decision["PPG Cost of Waiting"].fillna(0))

    # Boom gets more important in later rounds
    if decision_round <= 5:
        bw = .15
    elif decision_round <= 12:
        bw = .25
    else:
        bw = .40

    decision["Round Decision Score"] = (
        (0.30 - max(0, bw-.15)/2) * decision["PPG Score"] +
        0.25 * decision["Worth Score"] +
        0.15 * decision["Value Score"] +
        bw * decision["Boom Score"] +
        0.15 * decision["Urgency Score"]
    )

    if min_boom_games > 0:
        qualified = decision[decision[boom_col].fillna(-1) >= min_boom_games].copy()
    else:
        qualified = decision.copy()

    if qualified.empty:
        st.warning(
            f"No position in Round {decision_round} averaged at least "
            f"{min_boom_games:.1f} games at {boom_threshold}+ fantasy points. "
            f"Lower the minimum boom-games filter."
        )
    else:
        qualified = qualified.sort_values("Round Decision Score", ascending=False)
        winner = qualified.iloc[0]
        st.success(
            f"### Recommended Position: {winner['Position']} — approximately "
            f"**{winner['Available Now']}** is available entering Round {decision_round}."
        )

        cards = st.columns(4)
        for col, pos in zip(cards, ["QB","RB","WR","TE"]):
            row = decision[decision["Position"] == pos].iloc[0]
            with col:
                st.metric(pos, row["Available Now"])
                if pd.notna(row["Expected PPG"]):
                    st.caption(f"Expected: {row['Expected PPG']:.1f} PPG")
                st.caption(
                    f"If you wait: {row['If You Wait']} "
                    + (f"({row['Next Expected PPG']:.1f} PPG)" if pd.notna(row["Next Expected PPG"]) else "")
                )
                if pd.notna(row[boom_col]):
                    st.caption(f"Avg {boom_threshold}+ point games: {row[boom_col]:.1f}")
                if pd.notna(row["Worth-It %"]):
                    st.caption(f"Historical Worth-It: {row['Worth-It %']:.0f}%")
                st.caption(f"Decision Score: {row['Round Decision Score']:.1f}")

        st.subheader("Why the Model Likes This Position")
        st.write(
            f"Entering Round **{decision_round}**, the 2026 market suggests roughly "
            f"**{winner['Available Now']}** is available. Players who historically "
            f"**finished at that positional rank** averaged "
            f"**{winner['Expected PPG']:.1f} PPG**."
            if pd.notna(winner["Expected PPG"])
            else
            f"Entering Round **{decision_round}**, the 2026 market suggests roughly "
            f"**{winner['Available Now']}** is available."
        )

        if pd.notna(winner[boom_col]):
            st.write(
                f"For the selected upside target, historical Round {decision_round} "
                f"{winner['Position']}s averaged **{winner[boom_col]:.1f} games** "
                f"scoring at least **{boom_threshold} fantasy points**."
            )

        if pd.notna(winner["PPG Cost of Waiting"]):
            cost = winner["PPG Cost of Waiting"]
            if cost > 0:
                st.write(
                    f"Waiting one round moves the market toward **{winner['If You Wait']}** "
                    f"and historically costs about **{cost:.1f} PPG**."
                )
            elif cost < 0:
                st.write(
                    f"Historically the next positional rank actually averaged "
                    f"**{abs(cost):.1f} PPG more**, so there is little urgency to force this position."
                )
            else:
                st.write("The expected PPG is essentially unchanged if you wait one round.")

        st.subheader("All Positions — Current Market vs. Waiting")
        show = decision[[
            "Position","Available Now","Expected PPG","If You Wait","Next Expected PPG",
            "PPG Cost of Waiting",boom_col,"Worth-It %","Avg Value %","Sample",
            "Round Decision Score"
        ]].copy()

        show = show.rename(columns={
            boom_col: f"Avg {boom_threshold}+ Point Games"
        })

        st.dataframe(
            show.sort_values("Round Decision Score", ascending=False).round(1),
            use_container_width=True,
            hide_index=True
        )

        st.caption(
            f"Boom control is currently emphasizing **{boom_col}**. "
            "In later rounds, the recommendation automatically gives the higher-ceiling "
            "Boom game counts more weight."
        )


# ------------------------------------------------------------
# TAB 1
# ------------------------------------------------------------
with tab1:
    st.header("20-Round Snake Draft Plan")

    a,b,c,d = st.columns(4)
    slot = a.selectbox("Draft Slot", list(range(1,13)), index=7)
    style = b.selectbox("Risk Style", ["Balanced","High Upside","Safe"])
    build = c.selectbox("Opening Build", list(FORCED_BUILDS.keys()))
    window = d.slider("ADP Slide Window", 0, 24, 10)

    st.write(
        f"Your snake picks: **{' → '.join(map(str, snake_picks(slot)[:8]))} → ...**"
    )

    st.subheader("🔒 Optional Player Lock")
    l1, l2 = st.columns([1, 3])
    use_lock = l1.checkbox("Use player lock")
    locked_round = None
    locked_player = None

    if use_lock:
        locked_round = l1.selectbox("Lock Round", list(range(1,21)), index=0)
        locked_player = l2.selectbox(
            "Lock Player",
            pool["Player"].tolist(),
            index=0
        )
        locked_pick = snake_picks(slot)[locked_round-1]
        locked_rank = int(pool.loc[pool["Player"] == locked_player, "Rank"].iloc[0])
        st.caption(
            f"Locking **{locked_player}** into Round {locked_round} / Pick {locked_pick}. "
            f"Current 2026 rank: {locked_rank}."
        )

    plan = build_plan(
        slot, style, build, window,
        locked_round=locked_round,
        locked_player=locked_player
    )

    counts = plan["Position"].value_counts().to_dict()
    m1,m2,m3,m4 = st.columns(4)
    m1.metric("QB", counts.get("QB",0))
    m2.metric("RB", counts.get("RB",0))
    m3.metric("WR", counts.get("WR",0))
    m4.metric("TE", counts.get("TE",0))

    st.subheader("📊 Projected Best-Ball Score — Weeks 1–14")
    sim_count = 100
    st.caption("Projection uses 100 simulations for speed.")

    if "projection_result" not in st.session_state:
        st.session_state["projection_result"] = None
    if "projection_signature" not in st.session_state:
        st.session_state["projection_signature"] = None

    plan_signature = tuple(
        zip(
            plan["Round"].tolist(),
            plan["Player"].tolist(),
            plan["Position"].tolist()
        )
    )

    calc_projection = st.button(
        "Calculate 14-Week Projection",
        type="primary"
    )

    if calc_projection:
        with st.spinner(f"Running {sim_count} simulations..."):
            projection = project_roster_14_weeks(
                plan.to_dict("records"),
                simulations=sim_count,
                seed=42
            )
        st.session_state["projection_result"] = projection
        st.session_state["projection_signature"] = plan_signature

    projection = st.session_state.get("projection_result")
    projection_signature = st.session_state.get("projection_signature")

    if projection is not None and projection_signature == plan_signature:
        p1,p2,p3,p4 = st.columns(4)
        p1.metric(
            "Projected 14-Week Total",
            f"{projection['mean']:.1f}" if pd.notna(projection["mean"]) else "N/A"
        )
        p2.metric(
            "Projected Weekly Lineup",
            f"{projection['weekly_mean']:.1f}" if pd.notna(projection["weekly_mean"]) else "N/A"
        )
        p3.metric(
            "75th Percentile",
            f"{projection['p75']:.1f}" if pd.notna(projection["p75"]) else "N/A"
        )
        p4.metric(
            "90th Percentile",
            f"{projection['p90']:.1f}" if pd.notna(projection["p90"]) else "N/A"
        )

        st.caption(
            f"Projection uses {sim_count} simulated 14-week seasons. Each 2026 player is mapped to "
            "a precomputed historical weekly-score distribution from players who finished at the same "
            "positional rank. Each week automatically starts 1 QB, 2 RB, 3 WR, 1 TE and "
            "the highest-scoring remaining RB/WR/TE at FLEX."
        )
    else:
        st.info(
            "Projection is paused until you press **Calculate 14-Week Projection**. "
            "This keeps the app fast while you change draft slot, strategy, locks, or boom settings."
        )

    st.dataframe(
        plan.round({
            "Expected PPG":1,
            "Worth %":1,
            "Boom 20 Games":1,
            "Boom 25 Games":1,
            "Boom 30 Games":1,
            "Optimizer Score":1
        }),
        use_container_width=True,
        hide_index=True
    )

    st.info(
        "This is a strategy simulation, not a guarantee that every named player will be available. "
        "Use the On the Clock page during a real draft. "
        "**QB guardrails:** the auto-plan will not draft QBs back-to-back, will not take QB3 before Round 17, "
        "and will never intentionally build a 4-QB roster."
    )

# ------------------------------------------------------------
# TAB 2
# ------------------------------------------------------------
with tab2:
    st.header("On the Clock")

    c1,c2,c3,c4 = st.columns(4)
    live_slot = c1.selectbox("Your Draft Slot", list(range(1,13)), index=7, key="live_slot")
    live_round = c2.selectbox("Current Round", list(range(1,21)), key="live_round")
    live_style = c3.selectbox("Style", ["Balanced","High Upside","Safe"], key="live_style")
    live_boom = c4.selectbox(
        "Boom Focus",
        ["Auto","Boom 10 Games","Boom 15 Games","Boom 20 Games","Boom 25 Games","Boom 30 Games"],
        key="live_boom"
    )

    exact_pick = snake_picks(live_slot)[live_round-1]
    st.subheader(f"Round {live_round} — Pick {exact_pick}")

    drafted_names = st.multiselect(
        "Players already on YOUR roster",
        options=pool["Player"].tolist(),
        default=[]
    )

    my_rows = pool[pool["Player"].isin(drafted_names)]
    roster_positions = my_rows["Position"].tolist()

    # Remove manually drafted players from recommendation pool
    remaining = pool[~pool["Player"].isin(drafted_names)].copy()
    candidates = likely_available(remaining, exact_pick, window=12)
    scored = score_candidates(candidates, live_round, live_style, roster_positions)

    # Optional boom override for this specific round.
    if live_boom != "Auto" and live_boom in scored.columns:
        scored["Selected Boom Score"] = minmax(scored[live_boom].fillna(0))
        # Blend 30% selected boom target into the existing optimizer score.
        scored["Optimizer Score"] = (
            0.70 * scored["Optimizer Score"] +
            0.30 * scored["Selected Boom Score"]
        )
        scored = scored.sort_values("Optimizer Score", ascending=False)

    # Show best player and best option at each position
    top = scored.head(12).copy()
    st.subheader("Top Available Targets")
    show_cols = [
        "Rank","Player","POS","Team","Bye","Expected PPG","Worth %",
        "Boom 20 Games","Boom 25 Games","Boom 30 Games","Optimizer Score"
    ]
    st.dataframe(
        top[show_cols].round(1),
        use_container_width=True,
        hide_index=True
    )

    st.subheader("Best Choice by Position")
    by_pos = (
        scored.sort_values("Optimizer Score", ascending=False)
        .groupby("Position", as_index=False)
        .first()
        .sort_values("Optimizer Score", ascending=False)
    )
    st.dataframe(
        by_pos[["Position","Player","POS","Rank","Expected PPG","Worth %","Boom 20 Games","Boom 25 Games","Optimizer Score"]].round(1),
        use_container_width=True,
        hide_index=True
    )

    if not scored.empty:
        best = scored.iloc[0]
        counts = roster_counts(roster_positions)
        st.success(
            f"Recommendation: **{best['Player']} ({best['POS']})** — "
            f"{best['Position']} currently grades highest for your {live_style.lower()} build."
        )
        st.caption(
            f"Current roster: QB {counts['QB']} | RB {counts['RB']} | WR {counts['WR']} | TE {counts['TE']}"
        )

# ------------------------------------------------------------
# TAB 3
# ------------------------------------------------------------
with tab3:
    st.header("Player Performance vs. Ending-Rank Benchmark")
    st.caption(
        "For this section, End Rank is the player's final positional finish. The PPG benchmark comes from that "
        "End Rank's tier in your Finish Points sheet. A season counts as Worth It only if the player BOTH "
        "meets the end-rank PPG benchmark and finishes at or above the positional slot where he was drafted."
    )

    names = sorted(hist["Player"].dropna().unique())
    player = st.selectbox("Historical Player", names)
    ph = hist[hist["Player"] == player].copy().sort_values("Year")

    if ph.empty:
        st.warning("No historical seasons found.")
    else:
        ph["Draft Positional Label"] = (
            ph["Position"] + ph["Draft Pos Rank"].round().astype("Int64").astype(str)
        )

        worth_count = int(ph["Overall Worth It"].fillna(False).sum())
        total_count = int(ph["Overall Worth It"].notna().sum())
        avg_value = ph["Finish Benchmark %"].mean()

        x1,x2,x3,x4 = st.columns(4)
        x1.metric("Worth-It Seasons", f"{worth_count}/{total_count}")
        x2.metric("Avg vs Finish Benchmark", f"{avg_value:.1f}%" if pd.notna(avg_value) else "N/A")
        avg_rank_return = ph["Positional Rank Return"].mean()
        x3.metric(
            "Avg Rank Return",
            f"{avg_rank_return:+.1f}" if pd.notna(avg_rank_return) else "N/A",
            help="Positive = finished better than positional draft slot. Negative = finished worse."
        )
        best_year = ph.loc[ph["Finish Benchmark %"].idxmax(), "Year"] if ph["Finish Benchmark %"].notna().any() else "N/A"
        x4.metric("Best Benchmark Year", str(int(best_year)) if best_year != "N/A" else "N/A")

        chart = ph[["Year","AVG","Expected PPG at Finish"]].dropna().copy()
        chart["Year"] = chart["Year"].astype(int).astype(str)
        chart = chart.set_index("Year")
        chart.columns = ["Actual PPG","Expected PPG for Ending Rank"]
        st.line_chart(chart, x_label="Year", y_label="PPG")

        # Draft positional rank vs end-of-season rank.
        # Year is intentionally a string so labels display as 2022, not 2,022.
        rank_chart = ph[["Year","Draft Pos Rank","RK"]].dropna().copy()
        rank_chart["Year"] = rank_chart["Year"].astype(int).astype(str)
        rank_chart = rank_chart.set_index("Year")
        rank_chart.columns = ["Draft Positional Rank","End Rank"]
        st.line_chart(rank_chart, x_label="Year", y_label="Rank")

        display_cols = [
            "Year","Position","ADP","Draft Positional Label","RK","Finish Tier","AVG",
            "Expected PPG at Finish","Finish Benchmark %","Positional Rank Return",
            "Overall Worth It","Worth It Reason","Boom 20","Boom 25","Boom 30"
        ]
        history_table = ph[[c for c in display_cols if c in ph.columns]].copy()
        history_table = history_table.rename(columns={
            "RK": "End Rank",
            "Draft Positional Label": "Draft Pos Rank",
            "Expected PPG at Finish": "Expected PPG for End Rank",
            "Finish Benchmark %": "PPG vs End-Rank Benchmark %",
            "Positional Rank Return": "Rank Return",
            "Overall Worth It": "Worth It"
        })
        st.dataframe(
            history_table.round(1),
            use_container_width=True,
            hide_index=True
        )

        st.info(
            "**Worth It requires two tests:** (1) Actual PPG must meet the Finish Points benchmark for the player's "
            "End Rank, and (2) End Rank must be as good as or better than his positional draft rank. "
            "This prevents an injury-shortened season with strong PPG from being called a successful draft pick "
            "when the player still finished well below where he was selected."
        )


# ------------------------------------------------------------
# TAB 4 — ROOKIE ANALYSIS
# ------------------------------------------------------------
with tab4:
    st.header("Rookie ADP Performance")
    st.caption(
        "Only player-seasons marked as rookies in the workbook are included. "
        "This compares rookie positional ADP with End Rank, scoring, and spike-game upside."
    )

    rook = rookie_analysis_table()

    if rook.empty:
        st.warning("No rookie rows were found in the Rookie? column.")
    else:
        f1, f2, f3 = st.columns(3)

        pos_options = ["All"] + sorted(rook["Position"].dropna().unique().tolist())
        rookie_pos = f1.selectbox("Position", pos_options, key="rookie_pos")

        round_values = sorted(
            pd.to_numeric(rook["Round"], errors="coerce")
            .dropna().astype(int).unique().tolist()
        )
        rookie_round = f2.selectbox(
            "Draft Round",
            ["All"] + round_values,
            key="rookie_round"
        )

        year_values = sorted(rook["Year"].dropna().astype(int).unique().tolist())
        rookie_years = f3.multiselect(
            "Years",
            year_values,
            default=year_values,
            key="rookie_years"
        )

        rr = rook[rook["Year"].isin(rookie_years)].copy()
        if rookie_pos != "All":
            rr = rr[rr["Position"] == rookie_pos]
        if rookie_round != "All":
            rr = rr[pd.to_numeric(rr["Round"], errors="coerce") == int(rookie_round)]

        if rr.empty:
            st.info("No rookies match those filters.")
        else:
            m1, m2, m3, m4 = st.columns(4)

            worth_rate = rr["Overall Worth It"].mean() * 100
            avg_rank_return = rr["Positional Rank Return"].mean()
            beat_adp_rate = rr["Met Draft Rank"].mean() * 100
            avg_finish_benchmark = rr["Finish Benchmark %"].mean()

            m1.metric("Rookie Worth-It Rate", f"{worth_rate:.1f}%")
            m2.metric(
                "Avg Rank Return",
                f"{avg_rank_return:+.1f}",
                help="Positive means the rookie finished better than his positional draft slot."
            )
            m3.metric("Beat / Met Positional ADP", f"{beat_adp_rate:.1f}%")
            m4.metric(
                "Avg PPG vs End-Rank Benchmark",
                f"{avg_finish_benchmark:.1f}%"
            )

            st.subheader("Rookie Results")

            cols = [
                "Year","Player","Position","ADP","Draft Pos Rank","Round","RK","AVG",
                "Expected PPG at Finish","Finish Benchmark %","Positional Rank Return",
                "Overall Worth It","Worth It Reason","Boom 20","Boom 25","Boom 30"
            ]
            table = rr[[c for c in cols if c in rr.columns]].copy()
            table = table.rename(columns={
                "Draft Pos Rank":"Draft Positional Rank",
                "RK":"End Rank",
                "Expected PPG at Finish":"Expected PPG for End Rank",
                "Finish Benchmark %":"PPG vs End-Rank Benchmark %",
                "Positional Rank Return":"Rank Return",
                "Overall Worth It":"Worth It",
                "Boom 20":"20+ Point Games",
                "Boom 25":"25+ Point Games",
                "Boom 30":"30+ Point Games"
            })

            st.dataframe(
                table.sort_values(["Year","ADP"]).round(1),
                use_container_width=True,
                hide_index=True
            )

            st.subheader("Rookies by Draft Round and Position")

            summary = (
                rr.dropna(subset=["Round"])
                .groupby(["Round","Position"])
                .agg(
                    Rookies=("Player","count"),
                    Worth_It=("Overall Worth It","mean"),
                    Avg_Rank_Return=("Positional Rank Return","mean"),
                    Beat_ADP=("Met Draft Rank","mean"),
                    Avg_PPG=("AVG","mean"),
                    Avg_20_Plus=("Boom 20","mean"),
                    Avg_25_Plus=("Boom 25","mean"),
                    Avg_30_Plus=("Boom 30","mean")
                )
                .reset_index()
            )

            summary["Worth_It"] *= 100
            summary["Beat_ADP"] *= 100
            summary = summary.rename(columns={
                "Worth_It":"Worth-It %",
                "Avg_Rank_Return":"Avg Rank Return",
                "Beat_ADP":"Beat/Met ADP %",
                "Avg_PPG":"Avg PPG",
                "Avg_20_Plus":"Avg 20+ Games",
                "Avg_25_Plus":"Avg 25+ Games",
                "Avg_30_Plus":"Avg 30+ Games"
            })

            st.dataframe(
                summary.round(1),
                use_container_width=True,
                hide_index=True
            )

            st.subheader("Average Rookie Rank Return by Year")
            chart = (
                rr.groupby("Year")["Positional Rank Return"]
                .mean()
                .reset_index()
            )
            chart["Year"] = chart["Year"].astype(int).astype(str)
            chart = chart.set_index("Year")
            chart.columns = ["Average Rank Return"]
            st.bar_chart(chart, x_label="Year", y_label="Average Rank Return")

            st.info(
                "**Rank Return = Draft Positional Rank − End Rank.** "
                "Example: drafted WR12 and finished WR7 = +5. "
                "Drafted WR12 and finished WR25 = -13."
            )

# ------------------------------------------------------------
# TAB 5
# ------------------------------------------------------------
with tab5:
    st.header("How the Optimizer Thinks")

    st.markdown("""
### 1. 2026 rankings determine what is available
The `2026 ADP` sheet supplies the live player pool. Your draft slot creates your exact snake picks.

### 2. Positional rank is translated into historical expected production
If a 2026 player is **WR18**, the production estimate uses the historical average PPG of players who actually **finished WR18** from 2022–2025.

### 3. Historical draft value is still tracked separately
The model also asks how often players historically drafted in that positional tier returned enough production for the draft cost.

That gives us both:
- **Expected production**
- **Chance of returning draft value**

### 4. Boom game counts matter more later
Early picks emphasize expected production and avoiding busts.

As the draft moves later, the optimizer deliberately increases the weight of:
- Boom 20%
- Boom 25%
- Boom 30%

This reflects the fact that a late-round player with several huge weeks can be more useful in best ball than a low-ceiling player with a slightly higher average.

### 5. Risk-style options

**Safe**
Prioritizes PPG, Worth-It rate and lower-variance production.

**Balanced**
Mixes expected production, historical value and spike-week upside.

**High Upside**
Aggressively increases boom-score importance, especially after Round 12.

### 6. Opening-build locks
You can force:
- RB-RB
- WR-WR
- RB-WR
- WR-RB
- Hero RB
- Zero RB
- Early QB
- Early TE

After the forced opening rounds, the optimizer adjusts to the roster you created.

### 7. Roster construction changes marginal value
The optimizer does not treat every position equally after you draft it.

For example:
- Once you have two QBs, another QB is generally less valuable than needed WR/RB depth.
- WR depth gets extra value because DraftKings uses three WR spots plus a FLEX.
- As the draft gets late, the optimizer increasingly protects minimum roster needs.

### 8. What the Boom columns mean
`Boom 10`, `Boom 15`, `Boom 20`, `Boom 25`, and `Boom 30` are **spike-game counts** from your workbook.

They are **not percentages or hit rates**.

Example:

**Boom 20 = 18.5**

means the Boom-20 threshold for that player/group is **18.5 fantasy points**.

Higher numbers indicate more weekly scoring ceiling.

### 9. Round-specific Boom controls
On the **2026 Round Decision** page, choose which point threshold you want to emphasize.

For example:

**Round 15 + Boom 25 + minimum 18.0 points**

means the model only considers positions whose historical Round 15 players averaged at least
**18.0 fantasy points at the Boom-25 threshold**.

Round weighting changes automatically:

- Early rounds: expected PPG, value and safety matter more.
- Middle rounds: Boom 20 / Boom 25 become more important.
- Late rounds: Boom 25 / Boom 30 receive the strongest upside weight.

The **On the Clock** page also has a Boom Focus override for a specific pick.

### 10. Player locks
Turn on **Use player lock**, choose a round, and select a 2026 player.

That player is forced into that round, and every later recommendation is recalculated around the new roster construction.

### 11. Projected Weeks 1–14 Best-Ball score
The projection now runs **only when you press the Calculate button**.

Historical weekly distributions are precomputed once when the app loads, which prevents the app from repeatedly rebuilding the same data every time you change a dropdown.

The projection is fixed at **100 simulations** to keep the app responsive while you compare draft constructions.

The projection is not a simple sum of player PPG.

For every simulated week, the model generates a score for each drafted player using the historical weekly-score distribution of players who finished at the same positional rank.

It then automatically scores the best legal lineup:

- 1 QB
- 2 RB
- 3 WR
- 1 TE
- 1 FLEX (RB/WR/TE)

The displayed 14-week total is the average across 750 simulated seasons. The 75th and 90th percentile totals show the roster's upside range.

### Player-history Worth-It rule
For the player-history section, a season is **Worth It only when BOTH are true**:

1. **PPG test:** actual PPG met the Finish Points benchmark for the player's **End Rank**.
2. **Rank-return test:** the player's **End Rank** was equal to or better than his positional draft rank.

Example:

- Drafted RB4
- End Rank RB12
- PPG slightly above the RB11–15 finish benchmark

That season is still **Not Worth It**, because the player did not return the positional draft capital.

**Rank Return = Draft Positional Rank − End Rank**

Positive = beat draft slot.  
Negative = finished worse than draft slot.

### Player-history benchmark vs. draft-cost benchmark
The app now intentionally keeps **two different comparisons**:

1. **Draft-cost value** for the optimizer: what production should be expected from where a player was drafted at his position.
2. **Player-history graph**: what production should be expected from where the player actually finished (`RK`), using the `Finish Points` sheet.

For example, if A.J. Brown finishes WR5, his player-history benchmark uses the **WR3–5 Finish Points** value. If he finishes WR20, it uses the **WR16–25** value.

### Boom game counts
`Boom 10`, `Boom 15`, `Boom 20`, `Boom 25`, and `Boom 30` are counts of games reaching those point totals.

For example:

**Boom 25 = 3**

means the player had **3 games with at least 25 fantasy points**.

When the website averages a Round × Position group and shows **25+ point games = 3.0**, that means players in that group averaged three 25+ point games.

### QB diminishing returns
Best Ball only starts **one QB each week**, so QB depth has sharply diminishing marginal value.

The auto-plan now uses these guardrails:

- **No back-to-back QB selections**
- QB2 is mildly penalized in the early rounds
- **QB3 is blocked until Round 17**
- QB4 is effectively blocked
- A manual player lock can still override the rules if you intentionally want an unusual build

The goal is to prevent the optimizer from chasing raw QB scoring while ignoring the extra weekly lineup opportunities created by RB/WR/TE depth.

### Rookie Analysis
The Rookie Analysis page filters only player-seasons marked as rookies in the `Rookie?` column.

It shows:
- rookie positional draft rank
- End Rank
- Rank Return
- Worth-It rate
- PPG versus the End-Rank Finish Points benchmark
- 20+/25+/30+ point-game counts
- performance by draft round and position

**Rank Return = Draft Positional Rank − End Rank**

Positive = rookie beat his positional ADP.  
Negative = rookie finished worse than his positional ADP.

### Important
The Draft Plan is a heuristic simulation. ADP does not guarantee that a player will be available at a particular pick. Use **On the Clock** during the real draft to react to the actual board.
""")

st.caption("Data source: your 2022–2025 historical workbook plus your 2026 ADP rankings.")


# ------------------------------------------------------------
# TAB 6 — REDZONE PLAYER PROFILE
# ------------------------------------------------------------
with tab6:
    render_redzone_multiyear_tab()


# ------------------------------------------------------------
# TAB 7 — WEEKLY MATCHUPS & COMPARE
# ------------------------------------------------------------
with tab7:
    render_weekly_matchup_tab()
