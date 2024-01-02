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


def format_time_filter(seconds):
    minutes, seconds = divmod(seconds, 60)
    return f"{int(minutes):02d}:{int(seconds):02d}"


app.jinja_env.filters["format_time"] = format_time_filter


def is_saturday(date_str):
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    return date_obj.weekday() == 5


def fetch_user_data(username):
    data, *_ = (
        supabase_client.from_("results")
        .select("*")
        .eq("username", username)
        .order("time")
        .execute()
    )

    times_excluding_saturday = [
        entry["time"] for entry in data[1] if not is_saturday(entry["date"])
    ]
    fastest_time = min((entry["time"] for entry in data[1]), default=None)

    percentiles = [10, 25, 50, 75, 90]
    time_percentiles = np.percentile(times_excluding_saturday, percentiles)
    time_percentiles = time_percentiles[::-1]

    top_times = sorted(data[1], key=lambda entry: entry["time"])[:5]

    return {
        "fastest_time": fastest_time,
        "time_percentiles": dict(zip(percentiles, time_percentiles)),
        "all_entries": data[1],
        "top_times": top_times,
    }


def fetch_leaderboard(date_str):
    data, _ = (
        supabase_client.from_("results")
        .select("*")
        .eq("date", date_str)
        .order("time")
        .execute()
    )

    leaderboard = []

    prev_time = None
    rank = 0

    for entry in data[1]:
        if entry["time"] != prev_time:
            rank += 1

        prev_time = entry["time"]

        mm, ss = divmod(entry["time"], 60)
        formatted_time = f"{mm:02d}:{ss:02d}"

        leaderboard.append(
            {
                "Rank": rank,
                "Username": entry["username"],
                "Time": formatted_time,
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
    data, _ = (
        supabase_client.from_("results")
        .select("*")
        .order("time", desc=False)
        .limit(10)
        .execute()
    )
    return render_template("top_times.html", data=data[1])


@app.route("/recent_games")
def recent_games():
    data, _ = (
        supabase_client.from_("results")
        .select("*")
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    most_recent_date = datetime.strptime(data[1][0]["date"], "%Y-%m-%d")

    recent_dates = [
        (most_recent_date - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(10)
    ]

    return render_template("recent_games.html", recent_dates=recent_dates)


@app.route("/user/<username>")
def user(username):
    user_data = fetch_user_data(username)
    all_entries = user_data["all_entries"]

    if user_data is None:
        return redirect(url_for("leaderboard"))

    dates = [entry["date"] for entry in all_entries]
    times = [entry["time"] for entry in all_entries]

    sorted_indices = sorted(range(len(dates)), key=lambda k: dates[k])
    sorted_dates = [dates[i] for i in sorted_indices]
    sorted_times = [times[i] for i in sorted_indices]

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
            dict(dtickrange=[None, 1000], value="%H:%M:%S.%L ms"),
            dict(dtickrange=[1000, 60000], value="%H:%M:%S s"),
            dict(dtickrange=[60000, 3600000], value="%H:%M m"),
            dict(dtickrange=[3600000, 86400000], value="%H:%M h"),
            dict(dtickrange=[86400000, 604800000], value="%e. %b d"),
            dict(dtickrange=[604800000, "M1"], value="%e. %b w"),
            dict(dtickrange=["M1", "M12"], value="%b '%y M"),
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

        time = entry["score"]["secondsSpentSolving"]

        if time != prev_time:
            rank += 1
        prev_time = time

        result = {
            "Rank": rank,
            "Username": entry["name"],
            "Time": format_time_filter(time),
        }

        results.append(result)

    return render_template("today.html", leaderboard_data=results)


@app.route("/")
@app.route("/index/<data_source>")
def index(data_source="all"):
    def get_leaderboard_from_db(db_name):
        data, _ = (
            supabase_client.from_(db_name).select("*").order("elo", desc=True).execute()
        )

        output = []

        for rank, entry in enumerate(data[1], 1):
            mm, ss = divmod(int(entry["average_time"]), 60)
            formatted_time = f"{mm:02d}:{ss:02d}"

            output.append(
                {
                    "Rank": rank,
                    "Username": entry["username"],
                    "ELO": int(entry["elo"]),
                    "avg_time": formatted_time,
                    "num_wins": entry["num_wins"],
                    "num_played": entry["num_played"],
                }
            )

        return output

    all_data = get_leaderboard_from_db("all")
    last_30_data = get_leaderboard_from_db("last_30")
    last_90_data = get_leaderboard_from_db("last_90")

    if data_source == "all":
        selected_data = all_data
    elif data_source == "last_30":
        selected_data = last_30_data
    else:
        selected_data = last_90_data

    return render_template("home.html", data=selected_data)


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, "static"), "favicon.ico", mimetype="image/x-icon"
    )


if __name__ == "__main__":
    app.run(debug=True)
