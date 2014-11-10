from werkzeug.contrib.cache import FileSystemCache
from flask import Flask, render_template
import os

import requests
import json
from datetime import datetime
from multiprocessing.dummy import Pool as ThreadPool
from collections import defaultdict

app = Flask(__name__)
app.debug = True

cache = FileSystemCache("cache")
BASE_URL = "http://ws.audioscrobbler.com/2.0/?method=user.getrecenttracks&api_key=e62251fbec82fa75fa8c9a0ed17c5c17&format=json&limit=200&user={}&page={}"
MAX_PAGES_EVER = 400
POOL_SIZE = 10

@app.route("/")
def home():
    return "Visit /user/your-username/ -- Might take ~30 seconds to load if you have a lot of history."

@app.route("/user/<username>/")
@app.route("/user/<username>")
def details(username=None):
    songs = get_user_tracks(username)
    spring_freq = get_artist_frequency(get_songs_for_spring(songs))
    summer_freq = get_artist_frequency(get_songs_for_summer(songs))
    fall_freq = get_artist_frequency(get_songs_for_fall(songs))
    winter_freq = get_artist_frequency(get_songs_for_winter(songs))
    
    spring = make_actual_template_params(spring_freq)
    summer = make_actual_template_params(summer_freq)
    fall = make_actual_template_params(fall_freq)
    winter = make_actual_template_params(winter_freq)

    return render_template('main.html', spring=spring, summer=summer, winter=winter, fall=fall)


def make_actual_template_params(freq):
    count = 5 if len(freq) >= 5 else len(freq)

    songs = []
    for i in range(count):
        songs.append({"name": freq[i][0], "count": int(freq[i][1])})
    return songs

def get_songs_for_spring(songs):
    return get_songs_for_season(songs, range(80, 172))

def get_songs_for_summer(songs):
    return get_songs_for_season(songs, range(172, 264))

def get_songs_for_fall(songs):
    return get_songs_for_season(songs, range(264, 355))

def get_songs_for_winter(songs):
    return get_songs_for_season(songs, range(0, 80) + range(356, 365))

def get_songs_for_season(songs, season_days):
    return [s for s in songs if 'date' in s and datetime.utcfromtimestamp(float(s['date']['uts'])).timetuple().tm_yday in season_days]

def get_user_tracks(username):
    cached_value = cache.get(username)
    if cached_value:
        return cached_value

    page = 1
    songs = []

    # Ignore that this is the same as the method below, I need to
    # access the request object for the max page count too.
    url = BASE_URL.format(username, "1")

    req = requests.get(url)
    body = json.loads(req.text)

    if 'recenttracks' not in body:
        return []

    for track in body['recenttracks']['track']:
        songs.append(track)

    actualPageCount = int(body['recenttracks']['@attr']['totalPages'])
    max_pages = actualPageCount if actualPageCount < MAX_PAGES_EVER else MAX_PAGES_EVER
    page_sections = split_range_into_sections(range(2, max_pages), POOL_SIZE)
    pool_ranges = []
    
    for n in range(POOL_SIZE):
        pool_ranges.append((username, min(page_sections[n]), max(page_sections[n])))

    pool = ThreadPool(POOL_SIZE)
    results = pool.map(get_user_tracks_for_pages, pool_ranges)
    pool.close()
    pool.join()
    
    for r in results:
        songs += r

    cache.set(username, songs, timeout=60 * 60 * 24)
    return songs

def get_user_tracks_for_pages(d): #username, page_start, page_end):
    username = d[0]

    songs = []
    for page in range(d[1], d[2] + 1):
        url = BASE_URL.format(username, str(page))

        req = requests.get(url)
        body = json.loads(req.text)

        if 'recenttracks' not in body or 'track' not in body['recenttracks']:
            break

        for track in body['recenttracks']['track']:
            songs.append(track)

    return songs


def split_range_into_sections(seq, sections):
    seqlen = len(seq)
    d, m = divmod(seqlen, sections)
    rlist = range(0, ((d + 1) * (m + 1)), (d + 1))
    if d != 0: rlist += range(rlist[-1] + d, seqlen, d) + [seqlen]

    newseq = []
    for i in range(len(rlist) - 1):
        newseq.append(seq[rlist[i]:rlist[i + 1]])

    newseq += [[]] * max(0, (sections - seqlen))
    return newseq


def get_artist_frequency(songs):
    freqs = defaultdict(int)
    for song in songs:
        artist = song['artist']['#text']
        freqs[artist] += 1
    freqs = sorted(freqs.items(), key=lambda x: x[1], reverse=True)
    return freqs

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
