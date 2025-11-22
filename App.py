from flask import Flask, redirect, request, jsonify
from flask_cors import CORS
import requests
import urllib.parse
import secrets
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(16))

# Enable CORS
CORS(app, supports_credentials=True, origins=[
    'https://spotify-playlist-analyzer-ira.vercel.app',
    'http://localhost:3000',
    'http://localhost:5173'
])

# URLs
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'https://spotify-playlist-analyzer-ira.vercel.app')
BACKEND_URL = os.environ.get('BACKEND_URL', 'https://spotify-playlist-analyzer-production.up.railway.app')
REDIRECT_URI = f'{BACKEND_URL}/callback'

# API endpoints
SPOTIFY_AUTH_URL = 'https://accounts.spotify.com/authorize'
SPOTIFY_TOKEN_URL = 'https://accounts.spotify.com/api/token'
SPOTIFY_API_BASE_URL = 'https://api.spotify.com/v1'

# Scopes
SCOPE = 'user-read-private user-read-email playlist-read-private user-top-read'

@app.route('/')
def index():
    return jsonify({
        'status': 'Backend is running!',
        'endpoints': ['/login', '/callback', '/analyze', '/user_dashboard']
    })

@app.route('/login')
def login():
    params = {
        'client_id': CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': REDIRECT_URI,
        'scope': SCOPE,
        'show_dialog': True
    }
    auth_url = f"{SPOTIFY_AUTH_URL}?{urllib.parse.urlencode(params)}"
    return redirect(auth_url)

@app.route('/callback')
def callback():
    if 'error' in request.args:
        return redirect(f"{FRONTEND_URL}?error={request.args['error']}")
    
    if 'code' in request.args:
        code = request.args['code']
        token_data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': REDIRECT_URI,
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET
        }
        
        try:
            response = requests.post(SPOTIFY_TOKEN_URL, data=token_data)
            token_info = response.json()
            
            if 'access_token' not in token_info:
                return redirect(f"{FRONTEND_URL}?error=token_failed")
            
            # Instead of storing in session, pass token to frontend via URL
            access_token = token_info['access_token']
            return redirect(f"{FRONTEND_URL}?access_token={access_token}")
            
        except Exception as e:
            return redirect(f"{FRONTEND_URL}?error=callback_failed")
    
    return redirect(FRONTEND_URL)

def get_token_from_request():
    """Extract token from Authorization header"""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header.replace('Bearer ', '')
    return None

@app.route('/analyze', methods=['POST'])
def analyze():
    token = get_token_from_request()
    if not token:
        return jsonify({'error': 'Not authenticated', 'need_login': True}), 401
    
    data = request.get_json()
    playlist_url = data.get('playlist_url', '')
    
    try:
        playlist_id = playlist_url.split('playlist/')[-1].split('?')[0]
    except:
        return jsonify({'error': 'Invalid playlist URL'}), 400
    
    headers = {'Authorization': f"Bearer {token}"}
    
    try:
        playlist_response = requests.get(f'{SPOTIFY_API_BASE_URL}/playlists/{playlist_id}', headers=headers)
        if playlist_response.status_code != 200:
            return jsonify({'error': 'Failed to fetch playlist'}), 400
        
        playlist = playlist_response.json()
        tracks_response = requests.get(playlist['tracks']['href'], headers=headers)
        tracks_data = tracks_response.json().get('items', [])
        
        total_tracks = len(tracks_data)
        total_duration_ms = sum(item['track']['duration_ms'] for item in tracks_data if item['track'])
        total_duration_hours = round(total_duration_ms / (1000 * 60 * 60), 2)
        
        popularities = [item['track']['popularity'] for item in tracks_data if item['track']]
        avg_popularity = round(sum(popularities) / len(popularities)) if popularities else 0
        
        most_popular = max(tracks_data, key=lambda x: x['track']['popularity'] if x['track'] else 0)
        most_popular_track = most_popular['track']['name'] if most_popular['track'] else 'N/A'
        most_popular_artist = most_popular['track']['artists'][0]['name'] if most_popular['track'] and most_popular['track']['artists'] else 'N/A'
        
        artist_counts = {}
        for item in tracks_data:
            if item['track'] and item['track']['artists']:
                artist_name = item['track']['artists'][0]['name']
                artist_counts[artist_name] = artist_counts.get(artist_name, 0) + 1
        
        most_common_artist = max(artist_counts, key=artist_counts.get) if artist_counts else 'N/A'
        artist_count = artist_counts.get(most_common_artist, 0)
        
        return jsonify({
            'playlist_name': playlist['name'],
            'playlist_owner': playlist['owner']['display_name'],
            'stats': {
                'total_tracks': total_tracks,
                'avg_popularity': avg_popularity,
                'total_duration_hours': total_duration_hours,
                'most_popular_track': most_popular_track,
                'most_popular_artist': most_popular_artist,
                'most_common_artist': most_common_artist,
                'artist_count': artist_count
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/user_dashboard')
def user_dashboard():
    token = get_token_from_request()
    if not token:
        return jsonify({'error': 'Not authenticated', 'need_login': True}), 401

    headers = {'Authorization': f"Bearer {token}"}
    user_stats = {
        'top_artists': [],
        'top_tracks': [],
        'top_genres': []
    }
    personalized_insights = []

    try:
        # Get top artists
        response_artists = requests.get('https://api.spotify.com/v1/me/top/artists?limit=10', headers=headers)
        if response_artists.status_code == 200:
            items = response_artists.json().get('items', [])
            genre_counter = {}
            for artist in items:
                user_stats['top_artists'].append(artist['name'])
                for genre in artist.get('genres', []):
                    genre_counter[genre] = genre_counter.get(genre, 0) + 1
            sorted_genres = sorted(genre_counter.items(), key=lambda x: x[1], reverse=True)[:5]
            user_stats['top_genres'] = [g for g, _ in sorted_genres]
            if user_stats['top_artists']:
                personalized_insights.append(f"Your most played artist is {user_stats['top_artists'][0]}! You have great taste in music.")
            if len(set(g for g, _ in sorted_genres)) >= 3:
                top3 = [g for g, _ in sorted_genres[:3]]
                personalized_insights.append(f"You're into diverse music - your top genres are {', '.join(top3)}.")
            elif sorted_genres:
                personalized_insights.append(f"You're really into {sorted_genres[0][0]} music!")

        # Get top tracks
        response_tracks = requests.get('https://api.spotify.com/v1/me/top/tracks?limit=10', headers=headers)
        if response_tracks.status_code == 200:
            tracks = response_tracks.json().get('items', [])
            for t in tracks:
                artist_name = t['artists'][0]['name'] if t['artists'] else 'Unknown'
                user_stats['top_tracks'].append(f"{t['name']} - {artist_name}")
            if tracks:
                top_track = tracks[0]
                personalized_insights.append(f"Your current favorite track is '{top_track['name']}' by {top_track['artists'][0]['name']}.")
    except Exception as e:
        pass

    return jsonify({
        'user_stats': user_stats,
        'personalized_insights': personalized_insights
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)