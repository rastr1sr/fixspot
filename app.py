import re
import requests
from flask import Flask, request, redirect, Response, render_template_string
from urllib.parse import unquote
from datetime import datetime, timedelta
import logging
import os

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# --- Configuration ---
CACHE_DURATION_SECONDS = int(os.environ.get('CACHE_DURATION_SECONDS', 24 * 60 * 60)) # 24 hours default
CACHE_DURATION = timedelta(seconds=CACHE_DURATION_SECONDS)
USER_AGENT_BOTS = ["Discordbot", "TelegramBot", "facebookexternalhit", "Twitterbot", "Slackbot"]
SPOTIFY_OEMBED_URL = "https://open.spotify.com/oembed"
SERVICE_NAME = os.environ.get('SERVICE_NAME', 'Spotify Embed Fix')
YOUR_TWITTER_HANDLE = os.environ.get('YOUR_TWITTER_HANDLE', '')

# --- WARNING: Vercel Cache ---
# Vercel Serverless Functions are often stateless. This in-memory cache will likely reset.
# Use Vercel KV, Upstash, Momento, etc., for reliable caching in production.
cache = {}
# ---

def extract_spotify_track_id(url_string):
    """Extracts Spotify track ID from various URL/URI formats or direct ID."""
    if not url_string:
        return None
    try:
        # Handle direct ID first (common usage like your-app.com/TRACKID)
        if re.fullmatch(r'[a-zA-Z0-9]{22}', url_string):
             logging.debug(f"Assuming '{url_string}' is a direct Track ID.")
             return url_string

        decoded_url = unquote(url_string)
        # Match standard URLs and URIs
        match = re.search(r'(?:spotify\.com\/track\/|spotify:track:)([a-zA-Z0-9]{22})', decoded_url)
        if match:
            return match.group(1)
        return None
    except Exception as e:
        logging.error(f"Error parsing URL/ID '{url_string}': {e}")
        return None

def get_spotify_data(track_id):
    """Fetches data from Spotify oEmbed and handles caching."""
    now = datetime.utcnow()
    cache_key = f"spotify:{track_id}"

    if cache_key in cache:
        cached_data, expiry_time = cache[cache_key]
        if now < expiry_time:
            logging.info(f"Cache HIT for track ID: {track_id}")
            return cached_data
        else:
            logging.info(f"Cache EXPIRED for track ID: {track_id}")
            del cache[cache_key]
    else:
         logging.info(f"Cache MISS for track ID: {track_id}")

    original_url = f"https://open.spotify.com/track/{track_id}"
    params = {'url': original_url, 'format': 'json'}
    headers = {'User-Agent': f'{SERVICE_NAME}/1.0 (Vercel Function)'} # Identify your bot

    try:
        response = requests.get(SPOTIFY_OEMBED_URL, params=params, headers=headers, timeout=8)
        response.raise_for_status()
        data = response.json()

        required_keys = ['title', 'thumbnail_url', 'html']
        if not all(k in data for k in required_keys):
             logging.error(f"oEmbed response missing required keys for {track_id}. Data: {data}")
             return None

        embed_match = re.search(r'src="([^"]+)"', data['html'])
        width_match = re.search(r'width="(\d+)"', data['html'])
        height_match = re.search(r'height="(\d+)"', data['html'])

        if not embed_match:
            logging.error(f"Could not extract embed URL from oEmbed HTML for {track_id}")
            return None

        embed_url = embed_match.group(1)
        width = width_match.group(1) if width_match else "300"
        height = height_match.group(1) if height_match else "380" # Default to standard embed

        result_data = {
            'title': data.get('title', 'Spotify Track'),
            'thumbnail_url': data.get('thumbnail_url'),
            'original_url': original_url,
            'embed_url': embed_url,
            'width': width,
            'height': height,
            'provider_name': data.get('provider_name', 'Spotify'),
            'service_name': SERVICE_NAME,
            'your_twitter_handle': YOUR_TWITTER_HANDLE,
            'track_id': track_id
        }

        cache[cache_key] = (result_data, now + CACHE_DURATION)
        logging.info(f"Fetched and cached data for track ID: {track_id}")
        return result_data

    except requests.exceptions.Timeout:
        logging.error(f"Timeout fetching oEmbed for {track_id}")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Request error fetching oEmbed for {track_id}: {e}")
        return None
    except Exception as e:
        logging.error(f"Error processing oEmbed response for {track_id}: {e}")
        return None

HTML_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{{ title }}</title>
<meta property="og:title" content="{{ title }}"><meta property="og:description" content="Listen to {{ title }} on {{ provider_name }}."><meta property="og:site_name" content="{{ service_name }}"><meta property="og:url" content="{{ original_url }}">
{% if thumbnail_url %}<meta property="og:image" content="{{ thumbnail_url }}"><meta property="og:image:width" content="300"><meta property="og:image:height" content="300">{% endif %}
<meta property="og:type" content="video.other"><meta property="og:video" content="{{ embed_url }}"><meta property="og:video:secure_url" content="{{ embed_url }}"><meta property="og:video:type" content="text/html"><meta property="og:video:width" content="{{ width }}"><meta property="og:video:height" content="{{ height }}">
<meta name="twitter:card" content="player"><meta name="twitter:title" content="{{ title }}"><meta name="twitter:description" content="Listen on {{ provider_name }}">{% if your_twitter_handle %}<meta name="twitter:site" content="@{{ your_twitter_handle }}">{% endif %}{% if thumbnail_url %}<meta name="twitter:image" content="{{ thumbnail_url }}">{% endif %}<meta name="twitter:player" content="{{ embed_url }}"><meta name="twitter:player:width" content="{{ width }}"><meta name="twitter:player:height" content="{{ height }}">
<style>body{font-family:sans-serif;background-color:#191414;color:#fff;padding:20px} a{color:#1DB954}</style></head>
<body><h1>{{ title }}</h1><p>Track ID: {{ track_id }}</p><p>View on <a href="{{ original_url }}">Spotify</a>.</p></body></html>"""

ERROR_TEMPLATE = """<!DOCTYPE html>
<html><head><title>Error</title><style>body{font-family:sans-serif;padding:20px}</style></head>
<body><h1>Error</h1><p>{{ message }}</p></body></html>"""

LANDING_PAGE_TEMPLATE = """<!DOCTYPE html>
<html><head><title>{{ service_name }}</title><style>body{font-family:sans-serif;padding:20px;background-color:#191414;color:#fff;} a{color:#1DB954;} input[type=text]{width: 80%; padding: 10px; margin-bottom: 10px;} button{padding: 10px 15px;}</style></head>
<body><h1>{{ service_name }}</h1><p>Paste a Spotify track URL or ID below to generate an embed link.</p>
<form onsubmit="event.preventDefault(); window.location.href = '/' + document.getElementById('spotifyInput').value;">
<input type="text" id="spotifyInput" placeholder="https://open.spotify.com/track/..." required><br><button type="submit">Generate Link</button></form>
<p>Example usage: {{ request.host_url }}4cOdK2wGLETKBW3PvgPWqT</p>
</body></html>"""


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def handle_request(path):
    user_agent = request.headers.get('User-Agent', '')

    # Determine potential Spotify input from query or path
    input_value = request.args.get('url', path).strip()

    if not input_value:
        # Show a simple landing/instruction page if no input is provided
        return render_template_string(LANDING_PAGE_TEMPLATE, service_name=SERVICE_NAME, request=request), 200

    track_id = extract_spotify_track_id(input_value)

    if not track_id:
        logging.info(f"Could not extract valid Spotify track ID from input: '{input_value}'")
        return render_template_string(ERROR_TEMPLATE, message=f"Could not find a valid Spotify Track ID in '{input_value}'. Please provide a full Spotify track URL or just the 22-character ID."), 400

    # Check if the request is from a known bot
    is_bot = any(bot_ua in user_agent for bot_ua in USER_AGENT_BOTS)

    if is_bot:
        logging.info(f"Bot detected ({user_agent}), serving embed for track ID: {track_id}")
        spotify_data = get_spotify_data(track_id)

        if spotify_data:
            html_content = render_template_string(HTML_TEMPLATE, **spotify_data)
            return Response(html_content, mimetype='text/html')
        else:
            logging.warning(f"Could not get Spotify data for bot request {track_id}. Redirecting bot to original URL.")
            return redirect(f"https://open.spotify.com/track/{track_id}", code=307) # Temporary redirect
    else:
        # Not a known bot, redirect to the original Spotify URL
        logging.info(f"Non-bot user agent detected ({user_agent}), redirecting for track ID: {track_id}")
        return redirect(f"https://open.spotify.com/track/{track_id}", code=307) # Temporary redirect

@app.route('/favicon.ico')
def favicon():
    return '', 204

# No __main__ block needed for Vercel deployment
