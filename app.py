import os
from datetime import datetime, timedelta

import matplotlib.pyplot as plt
import numpy as np
import plotly
import plotly.graph_objects as go
import requests
from flask import Flask, render_template, request, send_from_directory
from flask_bootstrap import Bootstrap

from db import supabase_client
from utils import (
    fetch_leaderboard,
    fetch_live_leaderboard,
    fetch_today_leaderboard,
    format_time,
    get_most_recent_crossword_date,
    get_usernames_sorted_by_elo,
)

app = Flask(__name__)
bootstrap = Bootstrap(app)


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

    if not data:
        return None

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


def generate_plot_html(all_entries):
    sorted_entries = sorted(all_entries, key=lambda entry: entry["date"])
    sorted_dates, sorted_times = zip(
        *[(entry["date"], entry["time"]) for entry in sorted_entries]
    )

    if len(all_entries) > 1:
        fig = go.Figure()

        fig.add_trace(
            go.Scatter(
                x=sorted_dates, y=sorted_times, mode="markers", name="User Times"
            )
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
        return plotly.io.to_html(fig, include_plotlyjs=False, full_html=False)
    return "Need more times before we can plot!"


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
    most_recent_date = get_most_recent_crossword_date()

    recent_dates = [
        (most_recent_date - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(10)
    ]

    return render_template("recent_games.html", recent_dates=recent_dates)


@app.route("/user/<username>")
def user(username):
    user_data = fetch_user_data(username)
    if not user_data:
        return "User has no games in database yet. Check back later tonight!"

    plot_html = generate_plot_html(user_data["all_entries"])

    return render_template(
        "user.html", username=username, user_data=user_data, plot_html=plot_html
    )


@app.route("/today")
def today():
    data = fetch_live_leaderboard()
    solved_times = [entry["score"]["secondsSpentSolving"] for entry in data]

    results = []

    for entry in data:
        time = entry["score"]["secondsSpentSolving"]
        result = {
            "Rank": solved_times.index(time) + 1,
            "Username": entry["name"],
            "Time": format_time(time),
        }

        results.append(result)

    return render_template("today.html", leaderboard_data=results)


@app.route("/h2h")
@app.route("/h2h/<user1>/<user2>")
def h2h(user1=None, user2=None):
    stats = None
    users = get_usernames_sorted_by_elo()
    if user1 and user2:
        results = (
            supabase_client.rpc(
                "get_head_to_head_stats", {"user1": user1, "user2": user2}
            )
            .execute()
            .data
        )

        wins_user1 = 0
        wins_user2 = 0
        ties = 0
        total_matches = len(results)
        total_time_diff = 0
        avg_time_diff = 0

        for row in results:
            if row["time_player1"] < row["time_player2"]:
                wins_user1 += 1
            elif row["time_player1"] > row["time_player2"]:
                wins_user2 += 1
            else:
                ties += 1
            total_time_diff += row["time_player1"] - row["time_player2"]

        avg_time_diff = total_time_diff / total_matches if total_matches > 0 else 0
        faster_user, slower_user = (
            (user1, user2) if avg_time_diff < 0 else (user2, user1)
        )

        time_diff_description = f"On average, {faster_user} is {abs(avg_time_diff):.1f} seconds faster than {slower_user}."

        stats = {
            "wins_user1": wins_user1,
            "wins_user2": wins_user2,
            "ties": ties,
            "total_matches": total_matches,
            "time_diff_description": time_diff_description,
        }

    return render_template(
        "h2h.html", stats=stats, users=users, user1=user1, user2=user2
    )


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
