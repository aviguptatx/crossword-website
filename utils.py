import os
from datetime import datetime, timedelta

import requests

from db import supabase_client


def get_most_recent_crossword_date():
    data = (
        supabase_client.table("results")
        .select("*")
        .order("date", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return datetime.strptime(data[0]["date"], "%Y-%m-%d")


def fetch_leaderboard(date_str):
    data = (
        supabase_client.table("results")
        .select("*")
        .eq("date", date_str)
        .order("time")
        .execute()
        .data
    )

    times = [entry["time"] for entry in data]
    leaderboard = []

    for entry in data:
        leaderboard.append(
            {
                "Rank": times.index(entry["time"]) + 1,
                "Username": entry["username"],
                "Time": entry["time"],
            }
        )

    return leaderboard


def fetch_today_leaderboard():
    response = requests.get(
        "https://www.nytimes.com/svc/crosswords/v6/leaderboard/mini.json",
        headers={
            "accept": "application/json",
            "nyt-s": os.environ.get("NYT_S_TOKEN"),
        },
    )

    return response.json()["data"]


def format_time(seconds):
    minutes, seconds = divmod(seconds, 60)
    return f"{int(minutes):02d}:{int(seconds):02d}"
