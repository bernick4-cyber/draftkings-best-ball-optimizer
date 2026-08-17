
import streamlit as st
import pandas as pd
import numpy as np
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

# Player-history Worth It is based on WHAT YOU PAID:
# 1) Actual PPG must meet the expected PPG for the player's positional Draft Positional Rank.
# 2) End Rank must meet or beat the positional draft rank.
hist["Met ADP PPG Benchmark"] = hist["AVG"] >= hist["Expected PPG at Cost"]
hist["Overall Worth It"] = hist["Met ADP PPG Benchmark"] & hist["Met Draft Rank"]

# Percent of the ADP-based expected PPG that the player actually delivered.
hist["ADP PPG Value %"] = hist["AVG"] / hist["Expected PPG at Cost"] * 100

def worth_it_reason(row):
    if pd.isna(row["Draft Pos Rank"]) or pd.isna(row["RK"]):
        return "Insufficient data"
    if row["Overall Worth It"]:
        return "Met Draft Pos PPG expectation and returned draft rank"
    if not row["Met Draft Rank"] and not row["Met ADP PPG Benchmark"]:
        return "Missed both Draft Pos PPG expectation and draft-rank expectation"
    if not row["Met Draft Rank"]:
        return "PPG met ADP expectation, but End Rank finished below draft position"
    return "End Rank met draft slot, but PPG missed ADP expectation"

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

    # Rookie draft round is calculated directly from OVERALL ADP:
    # 1-12 = Round 1, 13-24 = Round 2, ... through Round 20.
    rookie_adp = pd.to_numeric(rook["ADP"], errors="coerce")
    rook["Rookie Draft Round"] = np.ceil(rookie_adp / 12.0)
    rook["Rookie Draft Round"] = rook["Rookie Draft Round"].clip(lower=1, upper=20)
    rook["Rookie Draft Round"] = rook["Rookie Draft Round"].astype("Int64")

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

# ============================================================
# UI
# ============================================================
st.title("🏈 DraftKings Best Ball Optimizer")
st.caption(
    "Uses your 2026 rankings for availability and your 2022–2025 results for historical "
    "production, draft value and spike-week upside."
)

tab0, tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🎯 2026 Round Decision",
    "🧠 Draft Plan",
    "⏱️ On the Clock",
    "📈 Player Value History",
    "🧪 Rookie Analysis",
    "📘 How It Works"
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
# TAB 3 — PLAYER VALUE HISTORY
# ------------------------------------------------------------
with tab3:
    st.header("Player Value History")
    st.caption(
        "Compare up to four players. Expected PPG is based on Draft Positional Rank "
        "(what you paid), while End Rank is used as the second test for whether the pick was Worth It."
    )

    names = sorted(hist["Player"].dropna().unique())
    selected_players = st.multiselect(
        "Players to compare",
        options=names,
        default=[names[0]] if names else [],
        max_selections=4
    )

    if not selected_players:
        st.info("Select at least one player to view history.")
    else:
        comp = hist[hist["Player"].isin(selected_players)].copy()

        st.subheader("🔍 Value Finder")
        st.caption(
            "Find the players who exceeded expectations the most based on Draft Positional Rank, "
            "End Rank, and PPG versus draft-cost expectation."
        )

        vf1, vf2, vf3, vf4 = st.columns(4)

        value_position = vf1.selectbox(
            "Position",
            ["All","QB","RB","WR","TE"],
            key="value_finder_pos"
        )

        value_year = vf2.selectbox(
            "Year",
            ["All"] + sorted(hist["Year"].dropna().astype(int).unique().tolist()),
            key="value_finder_year"
        )

        value_round = vf3.selectbox(
            "Draft Round",
            ["All"] + list(range(1,21)),
            key="value_finder_round"
        )

        value_sort = vf4.selectbox(
            "Rank By",
            [
                "PPG vs Draft Pos Expectation %",
                "Rank Return",
                "Worth It"
            ],
            key="value_finder_sort"
        )

        vf5, vf6 = st.columns(2)

        rookie_filter = vf5.selectbox(
            "Player Type",
            ["All","Rookies","Veterans"],
            key="value_finder_rookie"
        )

        top_n = vf6.slider(
            "Show Top",
            min_value=5,
            max_value=50,
            value=15,
            step=5,
            key="value_finder_topn"
        )

        value_df = hist.copy()

        # Calculate a clean 12-team draft round directly from overall ADP.
        value_df["Calculated Draft Round"] = np.ceil(
            pd.to_numeric(value_df["ADP"], errors="coerce") / 12.0
        ).clip(lower=1, upper=20)

        if value_position != "All":
            value_df = value_df[value_df["Position"] == value_position]

        if value_year != "All":
            value_df = value_df[value_df["Year"] == int(value_year)]

        if value_round != "All":
            value_df = value_df[
                value_df["Calculated Draft Round"] == int(value_round)
            ]

        if rookie_filter == "Rookies":
            value_df = value_df[value_df["Is Rookie"]]
        elif rookie_filter == "Veterans":
            value_df = value_df[~value_df["Is Rookie"]]

        if value_sort == "PPG vs Draft Pos Expectation %":
            value_df = value_df.sort_values(
                "ADP PPG Value %",
                ascending=False
            )
        elif value_sort == "Rank Return":
            value_df = value_df.sort_values(
                "Positional Rank Return",
                ascending=False
            )
        else:
            # Worth It first, then break ties by PPG value and rank return.
            value_df = value_df.sort_values(
                ["Overall Worth It","ADP PPG Value %","Positional Rank Return"],
                ascending=[False,False,False]
            )

        value_df = value_df.head(top_n).copy()

        if value_df.empty:
            st.info("No players match those Value Finder filters.")
        else:
            value_show = value_df[[
                "Year","Player","Position","ADP","Draft Pos Rank","RK","AVG",
                "Expected PPG at Cost","ADP PPG Value %",
                "Positional Rank Return","Overall Worth It",
                "Boom 20","Boom 25","Boom 30"
            ]].copy()

            value_show["Draft Pos Rank"] = value_show.apply(
                lambda r: (
                    f"{r['Position']}{int(r['Draft Pos Rank'])}"
                    if pd.notna(r["Draft Pos Rank"])
                    else None
                ),
                axis=1
            )

            value_show["RK"] = value_show.apply(
                lambda r: (
                    f"{r['Position']}{int(r['RK'])}"
                    if pd.notna(r["RK"])
                    else None
                ),
                axis=1
            )

            value_show = value_show.rename(columns={
                "Draft Pos Rank":"Draft Pos Rank",
                "RK":"End Rank",
                "Expected PPG at Cost":"Expected PPG for Draft Pos Rank",
                "ADP PPG Value %":"PPG vs Draft Pos Expectation %",
                "Positional Rank Return":"Rank Return",
                "Overall Worth It":"Worth It",
                "Boom 20":"20+ Point Games",
                "Boom 25":"25+ Point Games",
                "Boom 30":"30+ Point Games"
            })

            st.dataframe(
                value_show.round(1),
                use_container_width=True,
                hide_index=True
            )

            if value_sort == "PPG vs Draft Pos Expectation %":
                leader = value_df.iloc[0]
                st.success(
                    f"Biggest PPG value: **{leader['Player']}** delivered "
                    f"**{leader['ADP PPG Value %']:.1f}%** of the expected production "
                    f"for his Draft Positional Rank."
                )
            elif value_sort == "Rank Return":
                leader = value_df.iloc[0]
                st.success(
                    f"Biggest rank return: **{leader['Player']}** beat his Draft Positional Rank "
                    f"by **{leader['Positional Rank Return']:+.0f} spots**."
                )

        st.divider()

        summaries = []
        for player_name, ph in comp.groupby("Player"):
            worth_count = int(ph["Overall Worth It"].fillna(False).sum())
            total_count = int(ph["Overall Worth It"].notna().sum())
            summaries.append({
                "Player": player_name,
                "Seasons": len(ph),
                "Worth-It Seasons": f"{worth_count}/{total_count}",
                "Avg Actual PPG": ph["AVG"].mean(),
                "Avg PPG vs Draft Pos Expectation %": ph["ADP PPG Value %"].mean(),
                "Avg Rank Return": ph["Positional Rank Return"].mean(),
                "Beat / Met Draft Pos %": ph["Met Draft Rank"].mean() * 100
            })

        st.subheader("Comparison Summary")
        st.dataframe(
            pd.DataFrame(summaries).round(1),
            use_container_width=True,
            hide_index=True
        )

        st.subheader("Actual PPG by Year")
        ppg_chart = (
            comp[["Year","Player","AVG"]]
            .dropna()
            .assign(Year=lambda d: d["Year"].astype(int).astype(str))
            .pivot(index="Year", columns="Player", values="AVG")
            .sort_index()
        )
        st.line_chart(ppg_chart, x_label="Year", y_label="Actual PPG")

        st.subheader("PPG vs Draft Pos Expectation")
        value_chart = (
            comp[["Year","Player","ADP PPG Value %"]]
            .dropna()
            .assign(Year=lambda d: d["Year"].astype(int).astype(str))
            .pivot(index="Year", columns="Player", values="ADP PPG Value %")
            .sort_index()
        )
        st.line_chart(
            value_chart,
            x_label="Year",
            y_label="PPG vs Draft Pos Expectation %"
        )
        st.caption("100% means the player exactly met the PPG expectation for his Draft Positional Rank.")

        st.subheader("Rank Return")
        rank_return_chart = (
            comp[["Year","Player","Positional Rank Return"]]
            .dropna()
            .assign(Year=lambda d: d["Year"].astype(int).astype(str))
            .pivot(index="Year", columns="Player", values="Positional Rank Return")
            .sort_index()
        )
        st.bar_chart(
            rank_return_chart,
            x_label="Year",
            y_label="Rank Return"
        )
        st.caption("Positive = finished better than Draft Pos Rank. Negative = finished worse.")

        st.subheader("Draft Pos Rank vs End Rank")
        rank_rows = comp[["Year","Player","Position","Draft Pos Rank","RK"]].dropna().copy()
        rank_rows["Year"] = rank_rows["Year"].astype(int).astype(str)
        rank_rows["Draft Pos Rank"] = rank_rows.apply(
            lambda r: f"{r['Position']}{int(r['Draft Pos Rank'])}", axis=1
        )
        rank_rows["End Rank"] = rank_rows.apply(
            lambda r: f"{r['Position']}{int(r['RK'])}", axis=1
        )
        rank_rows = rank_rows.drop(columns=["RK"])
        st.dataframe(
            rank_rows.sort_values(["Player","Year"]),
            use_container_width=True,
            hide_index=True
        )

        st.subheader("Detailed Seasons")
        detail_cols = [
            "Year","Player","Position","ADP","Draft Positional Label","RK","AVG",
            "Expected PPG at Cost","ADP PPG Value %","Positional Rank Return",
            "Overall Worth It","Worth It Reason","Boom 20","Boom 25","Boom 30"
        ]
        detail = comp[[c for c in detail_cols if c in comp.columns]].copy()

        if "RK" in detail.columns:
            detail["RK"] = detail.apply(
                lambda r: (
                    f"{r['Position']}{int(r['RK'])}"
                    if pd.notna(r["RK"]) and pd.notna(r["Position"])
                    else None
                ),
                axis=1
            )

        detail = detail.rename(columns={
            "Draft Positional Label": "Draft Pos Rank",
            "RK": "End Rank",
            "Expected PPG at Cost": "Expected PPG for Draft Pos Rank",
            "ADP PPG Value %": "PPG vs Draft Pos Expectation %",
            "Positional Rank Return": "Rank Return",
            "Overall Worth It": "Worth It",
            "Boom 20": "20+ Point Games",
            "Boom 25": "25+ Point Games",
            "Boom 30": "30+ Point Games"
        })

        st.dataframe(
            detail.sort_values(["Player","Year"]).round(1),
            use_container_width=True,
            hide_index=True
        )

        st.info(
            "**Worth It requires both:** the player must meet the PPG expectation for his Draft Positional Rank "
            "and finish at or above that Draft Positional Rank."
        )

# ------------------------------------------------------------
# TAB 4 — ROOKIE ANALYSIS
# ------------------------------------------------------------
with tab4:
    st.header("Rookie ADP Performance")
    st.caption(
        "Only player-seasons marked as rookies in the workbook are included. "
        "Rookie Round is calculated from overall ADP using a 12-team draft: "
        "ADP 1–12 = Round 1, 13–24 = Round 2, and so on through Round 20."
    )

    rook = rookie_analysis_table()

    if rook.empty:
        st.warning("No rookie rows were found in the Rookie? column.")
    else:
        f1, f2, f3 = st.columns(3)

        pos_options = ["All"] + sorted(rook["Position"].dropna().unique().tolist())
        rookie_pos = f1.selectbox("Position", pos_options, key="rookie_pos")

        round_values = sorted(
            pd.to_numeric(rook["Rookie Draft Round"], errors="coerce")
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
            rr = rr[pd.to_numeric(rr["Rookie Draft Round"], errors="coerce") == int(rookie_round)]

        if rr.empty:
            st.info("No rookies match those filters.")
        else:
            m1, m2, m3, m4 = st.columns(4)

            worth_rate = rr["Overall Worth It"].mean() * 100
            avg_rank_return = rr["Positional Rank Return"].mean()
            beat_adp_rate = rr["Met Draft Rank"].mean() * 100
            avg_finish_benchmark = rr["ADP PPG Value %"].mean()

            m1.metric("Rookie Worth-It Rate", f"{worth_rate:.1f}%")
            m2.metric(
                "Avg Rank Return",
                f"{avg_rank_return:+.1f}",
                help="Positive means the rookie finished better than his positional draft slot."
            )
            m3.metric("Beat / Met Positional ADP", f"{beat_adp_rate:.1f}%")
            m4.metric(
                "Avg PPG vs Draft Pos Expectation",
                f"{avg_finish_benchmark:.1f}%"
            )

            st.subheader("Rookie Results")

            cols = [
                "Year","Player","Position","ADP","Draft Pos Rank","Rookie Draft Round","RK","AVG",
                "Expected PPG at Cost","ADP PPG Value %","Positional Rank Return",
                "Overall Worth It","Worth It Reason","Boom 20","Boom 25","Boom 30"
            ]
            table = rr[[c for c in cols if c in rr.columns]].copy()

            # Show End Rank with the position prefix: WR6, RB12, QB3, TE8.
            if "RK" in table.columns:
                table["RK"] = table.apply(
                    lambda r: (
                        f"{r['Position']}{int(r['RK'])}"
                        if pd.notna(r["RK"]) and pd.notna(r["Position"])
                        else None
                    ),
                    axis=1
                )

            table = table.rename(columns={
                "Draft Pos Rank":"Draft Positional Rank",
                "Rookie Draft Round":"Round",
                "RK":"End Rank",
                "Expected PPG at Cost":"Expected PPG for Draft Pos Rank",
                "ADP PPG Value %":"PPG vs Draft Pos Expectation %",
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
                rr.dropna(subset=["Rookie Draft Round"])
                .groupby(["Rookie Draft Round","Position"])
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
                "Rookie Draft Round":"Round",
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
For the player-history section, the PPG expectation is based on **Draft Positional Rank — what you paid**.

A season is **Worth It only when BOTH are true**:

1. **PPG test:** actual PPG met the Finish Points expectation for the player's **positional Draft Positional Rank**.
2. **Rank-return test:** the player's **End Rank** was equal to or better than his positional draft rank.

Example:

- Drafted RB4
- Expected PPG comes from the RB3–5 ADP-cost tier
- End Rank RB12

Even if his PPG was respectable, that season is **Not Worth It** if he failed the Draft Pos PPG expectation or finished below RB4.

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

### Value Finder
The Player Value History page includes a Value Finder that can rank players by:

- **PPG vs Draft Pos Expectation %** — who most exceeded the scoring expectation attached to their Draft Positional Rank.
- **Rank Return** — who finished the most positional spots above where they were drafted.
- **Worth It** — players who passed both the scoring-expectation test and End-Rank test.

You can filter by position, year, 12-team draft round, and rookie/veteran status.

### Rookie Analysis
The Rookie Analysis page filters only player-seasons marked as rookies in the `Rookie?` column.

Rookie draft round is calculated directly from overall ADP for a 12-team draft:

- ADP 1–12 = Round 1
- ADP 13–24 = Round 2
- ADP 25–36 = Round 3
- and so on
- picks beyond 240 are grouped into Round 20

It shows:
- rookie positional draft rank
- End Rank
- Rank Return
- Worth-It rate
- PPG versus the ADP-rank Finish Points expectation
- 20+/25+/30+ point-game counts
- performance by draft round and position

**Rank Return = Draft Positional Rank − End Rank**

Positive = rookie beat his Draft Positional Rank.  
Negative = rookie finished worse than his Draft Positional Rank.

### Important
The Draft Plan is a heuristic simulation. ADP does not guarantee that a player will be available at a particular pick. Use **On the Clock** during the real draft to react to the actual board.
""")

st.caption("Data source: your 2022–2025 historical workbook plus your 2026 Draft Positional Rankings.")
