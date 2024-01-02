import os
from datetime import datetime, timedelta

import matplotlib.pyplot as plt
import numpy as np
import plotly
import plotly.graph_objects as go
import requests
import supabase
from flask import Flask, render_template, request, send_from_directory
from flask_bootstrap import Bootstrap

from db import supabase_client

app = Flask(__name__)
bootstrap = Bootstrap(app)


def format_time(seconds):
    minutes, seconds = divmod(seconds, 60)
    return f"{int(minutes):02d}:{int(seconds):02d}"


app.jinja_env.filters["format_time"] = format_time


def is_saturday(date_str):
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    return date_obj.weekday() == 5


def fetch_user_data(username):
    PERCENTILES = [10, 25, 50, 75, 90]

    data = (
        supabase_client.table("results")
        .select("*")
        .eq("username", username)
        .order("time")
        .execute()
        .data
    )

    times_excluding_saturday = [
        entry["time"] for entry in data if not is_saturday(entry["date"])
    ]
    fastest_time = min(entry["time"] for entry in data)

    time_percentiles = np.percentile(times_excluding_saturday, PERCENTILES)
    time_percentiles = time_percentiles[::-1]

    top_times = sorted(data, key=lambda entry: entry["time"])[:5]

    return {
        "fastest_time": fastest_time,
        "time_percentiles": dict(zip(PERCENTILES, time_percentiles)),
        "all_entries": data,
        "top_times": top_times,
    }


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
                "Time": format_time(entry["time"]),
            }
        )

    return leaderboard


@app.route("/history/<date>")
def history(date):
    leaderboard_data = fetch_leaderboard(date)
    return render_template(
        "history.html", date_str=date, leaderboard_data=leaderboard_data
    )


@app.route("/top_times")
def top_times():
    data = (
        supabase_client.table("results")
        .select("*")
        .order("time", desc=False)
        .limit(10)
        .execute()
        .data
    )
    return render_template("top_times.html", data=data)


@app.route("/recent_games")
def recent_games():
    data = (
        supabase_client.table("results")
        .select("*")
        .order("date", desc=True)
        .limit(1)
        .execute()
        .data
    )
    most_recent_date = datetime.strptime(data[0]["date"], "%Y-%m-%d")

    recent_dates = [
        (most_recent_date - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(10)
    ]

    return render_template("recent_games.html", recent_dates=recent_dates)


@app.route("/user/<username>")
def user(username):
    user_data = fetch_user_data(username)
    all_entries = user_data["all_entries"]

    sorted_entries = sorted(all_entries, key=lambda entry: entry["date"])
    sorted_dates, sorted_times = zip(
        *[(entry["date"], entry["time"]) for entry in sorted_entries]
    )

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(x=sorted_dates, y=sorted_times, mode="markers", name="User Times")
    )
    fig.add_trace(
        go.Scatter(
            x=sorted_dates,
            y=np.poly1d(np.polyfit(range(len(sorted_dates)), sorted_times, 1))(
                range(len(sorted_dates))
            ),
            mode="lines",
            name="Trend Line",
        )
    )

    fig.update_layout(
        xaxis_title="Date",
        yaxis_title="Time (seconds)",
        autosize=True,
        xaxis_tickformatstops=[
            dict(dtickrange=[None, "M1"], value="%b %e"),
            dict(dtickrange=["M1", "M12"], value="%b '%Y"),
            dict(dtickrange=["M12", None], value="%Y Y"),
        ],
    )

    plot_html = plotly.io.to_html(fig, include_plotlyjs=False, full_html=False)

    return render_template(
        "user.html", username=username, user_data=user_data, plot_html=plot_html
    )


@app.route("/today")
def today():
    response = requests.get(
        "https://www.nytimes.com/svc/crosswords/v6/leaderboard/mini.json",
        headers={
            "accept": "application/json",
            "nyt-s": os.environ.get("NYT_S_TOKEN"),
        },
    )

    results = []
    prev_time = None
    rank = 0

    for entry in response.json()["data"]:
        if "score" not in entry or entry["score"]["secondsSpentSolving"] == 0:
            continue

        curr_time = entry["score"]["secondsSpentSolving"]

        if curr_time != prev_time:
            rank += 1

        prev_time = curr_time

        result = {
            "Rank": rank,
            "Username": entry["name"],
            "Time": format_time(curr_time),
        }

        results.append(result)

    return render_template("today.html", leaderboard_data=results)


@app.route("/")
@app.route("/index/<data_source>")
def index(data_source="all"):
    def get_leaderboard_from_db(db_name):
        data = (
            supabase_client.table(db_name)
            .select("*")
            .order("elo", desc=True)
            .execute()
            .data
        )

        output = []

        for rank, entry in enumerate(data, 1):
            output.append(
                {
                    "Rank": rank,
                    "Username": entry["username"],
                    "ELO": int(entry["elo"]),
                    "avg_time": format_time(entry["average_time"]),
                    "num_wins": entry["num_wins"],
                    "num_played": entry["num_played"],
                }
            )

        return output

    return render_template("home.html", data=get_leaderboard_from_db(data_source))


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, "static"), "favicon.ico", mimetype="image/x-icon"
    )


if __name__ == "__main__":
    app.run(debug=True)
