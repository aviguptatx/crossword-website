import os
from datetime import datetime, timedelta

import pytz
import requests

from db import supabase_client


def to_iso(datetime_obj):
    return datetime_obj.strftime("%Y-%m-%d")


def today_eastern():
    utc_now = datetime.utcnow()
    et_now = utc_now.replace(tzinfo=pytz.utc).astimezone(pytz.timezone("US/Mountain"))
    return et_now


def daterange(start_date, end_date):
    for n in range(int((end_date - start_date).days) + 1):
        yield start_date + timedelta(n)


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
    today_iso = to_iso(today_eastern())

    response = requests.get(
        f"https://www.nytimes.com/svc/crosswords/v6/leaderboard/mini/{today_iso}.json",
        headers={
            "accept": "application/json",
            "nyt-s": os.environ.get("NYT_S_TOKEN"),
        },
    )

    return [
        entry
        for entry in response.json()["data"]
        if entry.get("score", {}).get("secondsSpentSolving", 0)
    ]


def format_time(seconds):
    minutes, seconds = divmod(seconds, 60)
    return f"{int(minutes):02d}:{int(seconds):02d}"
