import os
from datetime import datetime, timedelta

import matplotlib.pyplot as plt
import numpy as np
import plotly
import plotly.graph_objects as go
import requests
from flask import Flask, render_template, request, send_from_directory, redirect
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

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def redirect_to_new_site(path):
    new_website = "https://crosselo.avigupta.workers.dev/" + path
    return redirect(new_website, code=301)

if __name__ == "__main__":
    app.run(debug=True)
