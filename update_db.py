import os
from collections import defaultdict
from datetime import datetime, timedelta

import requests
import trueskill
from trueskill import Rating, rate

from db import supabase_client
from utils import (
    fetch_leaderboard,
    fetch_today_leaderboard,
    get_most_recent_crossword_date,
)


def fetch_today_results():
    results = []

    today_iso = datetime.now().isoformat()

    data = fetch_today_leaderboard()
    for entry in data:
        if "score" not in entry or entry["score"]["secondsSpentSolving"] == 0:
            continue

        result = {
            "date": today_iso,
            "username": entry["name"],
            "time": entry["score"]["secondsSpentSolving"],
        }

        results.append(result)

    return results


def compute_stats(
    start_date,
    end_date,
    mus=None,
    sigmas=None,
    num_wins=None,
    num_played=None,
    total_time=None,
    all_usernames=None,
):
    mus = mus or dict()
    sigmas = sigmas or dict()
    num_wins = num_wins or defaultdict(int)
    num_played = num_played or defaultdict(int)
    total_time = total_time or defaultdict(int)
    all_usernames = all_usernames or set()

    step = timedelta(days=1)

    current_iteration = start_date

    while current_iteration <= end_date:
        trueskills = []
        ranks = []
        usernames = []

        iso_date = current_iteration.date().isoformat()
        leaderboard = fetch_leaderboard(iso_date)

        if leaderboard:
            usernames = [entry["Username"] for entry in leaderboard]
            all_usernames.update(usernames)
            trueskills = [
                Rating(
                    mus.get(username, trueskill.MU),
                    sigmas.get(username, trueskill.SIGMA),
                )
                for username in usernames
            ]
            ranks = [entry["Rank"] - 1 for entry in leaderboard]

            for i, entry in enumerate(leaderboard):
                if ranks[i] == 0:
                    num_wins[usernames[i]] += 1
                num_played[usernames[i]] += 1
                total_time[usernames[i]] += entry["Time"]

            trueskills_tuples = [(x,) for x in trueskills]
            results = rate(trueskills_tuples, ranks=ranks)
            for i, result in enumerate(results):
                mus[usernames[i]] = result[0].mu
                sigmas[usernames[i]] = result[0].sigma

        current_iteration += step

    entries = []

    for username in all_usernames:
        table_entry = {
            "username": username,
            "mu": mus[username],
            "sigma": sigmas[username],
            "elo": (mus[username] - 3 * sigmas[username]) * 60,
            "average_time": total_time[username] / num_played[username],
            "num_played": num_played[username],
            "num_wins": num_wins[username],
        }
        entries.append(table_entry)

    return entries


def fetch_new_stats():
    mus = dict()
    sigmas = dict()
    num_wins = defaultdict(int)
    num_played = defaultdict(int)
    total_time = defaultdict(int)
    all_usernames = set()

    old_data = supabase_client.from_("all").select("*").execute().data
    for entry in old_data:
        username = entry["username"]
        all_usernames.add(username)
        mus[username] = entry["mu"]
        sigmas[username] = entry["sigma"]
        num_wins[username] = entry["num_wins"]
        num_played[username] = entry["num_played"]
        total_time[username] = entry["num_played"] * entry["average_time"]

    return old_data, compute_stats(
        datetime.now(),
        datetime.now(),
        mus,
        sigmas,
        num_wins,
        num_played,
        total_time,
        all_usernames,
    )


def update_table(table_name, data):
    supabase_client.table(table_name).delete().neq("id", -1).execute()
    for entry in data:
        supabase_client.table(table_name).insert(entry).execute()


if __name__ == "__main__":
    current_date = get_most_recent_crossword_date()

    for result in fetch_today_results():
        supabase_client.table("results").insert(result).execute()

    last_30_entries = compute_stats(
        start_date=current_date - timedelta(days=29), end_date=current_date
    )
    last_90_entries = compute_stats(
        start_date=current_date - timedelta(days=89), end_date=current_date
    )
    all_old, all_new = fetch_new_stats()

    update_table("last_30", last_30_entries)
    update_table("last_90", last_90_entries)
    update_table("all", all_new)

    print(all_old)
    print(all_new)
