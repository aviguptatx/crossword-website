import supabase
from datetime import datetime, timedelta
import trueskill
from trueskill import Rating, rate
from collections import defaultdict
from db import supabase_client


def fetch_leaderboard(date_str):
    data, _ = (
        supabase_client.from_("results")
        .select("*")
        .eq("date", date_str)
        .order("time")
        .execute()
    )

    leaderboard = []

    prev_score = None
    rank = 0

    for entry in data[1]:
        if entry["time"] != prev_score:
            rank += 1

        leaderboard.append(
            {
                "Rank": rank,
                "Username": entry["username"],
                "Time": entry["time"],
            }
        )

    return leaderboard


def update_results():
    today_iso = datetime.now().date().isoformat()

    response = requests.get(
        "https://www.nytimes.com/svc/crosswords/v6/leaderboard/mini.json",
        headers={
            "accept": "application/json",
            "nyt-s": "1wKc338dMaXaEkV7ViyXYFIRk62A8t4ZPiL5fY5rnr1hHKGa8MCmcj9gMItd1kb.sGjOoea6bgYnRxckKfk3fLpzAembwXpdiEzZc8xynz9R4swkK98XcatPxDTQO38FS1^^^^CBUSKwjcp-efBhCHnvmnBhoSMS1m-DM3NmZTD6rjR_kLyndcIOy4gF84iYftmQYaQH_rL-OPO34VpvDHmGBPalTjX7WbgzClvIgNC3TIGlgGMWkrfv-p-Y4e9n5YhqRXwOdEb53uKMw59wiDzXBEWAE",
        },
    )

    for entry in response.json()["data"]:
        if "score" not in entry or entry["score"]["secondsSpentSolving"] == 0:
            continue

        result = {
            "date": today_iso,
            "username": entry["name"],
            "time": entry["score"]["secondsSpentSolving"],
        }

        supabase_client.table("results").insert(result).execute()


def fetch_all_elos():
    mus = dict()
    sigmas = dict()
    num_wins = defaultdict(int)
    num_played = defaultdict(int)
    total_time = defaultdict(int)

    data, _ = supabase_client.from_("all").select("*").execute()
    for entry in data[1]:
        username = entry["username"]
        mus[username] = entry["mu"]
        sigmas[username] = entry["sigma"]
        num_wins[username] = entry["num_wins"]
        num_played[username] = entry["num_played"]
        total_time[username] = entry["total_time"]

    trueskills = []
    ranks = []
    usernames = []

    iso_date = datetime.now().date().isoformat()
    leaderboard = fetch_leaderboard(iso_date)
    if leaderboard:
        for entry in leaderboard:
            rank = entry["Rank"] - 1
            username = entry["Username"]
            trueskills.append(
                Rating(
                    mus.get(username, trueskill.MU),
                    sigmas.get(username, trueskill.SIGMA),
                )
            )
            ranks.append(rank)
            usernames.append(username)

            if rank == 0:
                num_wins[username] += 1
            num_played[username] += 1
            total_time[username] += entry["Time"]

        trueskills_tuples = [(x,) for x in trueskills]
        results = rate(trueskills_tuples, ranks=ranks)
        for i, result in enumerate(results):
            mus[usernames[i]] = result[0].mu
            sigmas[usernames[i]] = result[0].sigma

        entries = []

        for username in usernames:
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


def fetch_elos(start_date, end_date):
    all_usernames = set()
    mus = dict()
    sigmas = dict()
    num_wins = defaultdict(int)
    num_played = defaultdict(int)
    total_time = defaultdict(int)

    step = timedelta(days=1)

    current_iteration = start_date

    while current_iteration <= end_date:
        trueskills = []
        ranks = []
        usernames = []

        iso_date = current_iteration.date().isoformat()
        leaderboard = fetch_leaderboard(iso_date)
        if leaderboard:
            for entry in leaderboard:
                rank = entry["Rank"] - 1
                username = entry["Username"]
                trueskills.append(
                    Rating(
                        mus.get(username, trueskill.MU),
                        sigmas.get(username, trueskill.SIGMA),
                    )
                )
                ranks.append(rank)
                usernames.append(username)

                all_usernames.add(username)

                if rank == 0:
                    num_wins[username] += 1
                num_played[username] += 1
                total_time[username] += entry["Time"]

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


if __name__ == "__main__":
    update_results()

    current_date = datetime.now()

    supabase_client.table("last_30").delete().execute()
    last_30_entries = fetch_elos(current_date - timedelta(days=29), current_date)
    for entry in last_30_entries:
        supabase_client.table("last_30").insert(entry).execute()

    supabase_client.table("last_90").delete().execute()
    last_90_entries = fetch_elos(current_date - timedelta(days=89), current_date)
    for entry in last_90_entries:
        supabase_client.table("last_90").insert(entry).execute()

    all_entries = fetch_all_elos()
    supabase_client.table("all").delete().execute()
    for entry in all_entries:
        supabase_client.table("all").insert(entry).execute()
