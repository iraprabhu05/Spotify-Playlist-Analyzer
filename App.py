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

# Spotify API credentials
CLIENT_ID = os.environ.get('CLIENT_ID', 'f35352ea09ec4a3db35281095f8e5f3d')
CLIENT_SECRET = os.environ.get('CLIENT_SECRET', '99523569658b41c596afbd5b3b657974')

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

def get_client_credentials_token():
    """Get access token using client credentials flow for public playlists"""
    try:
        auth_response = requests.post(SPOTIFY_TOKEN_URL, data={
            'grant_type': 'client_credentials',
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET
        })
        if auth_response.status_code == 200:
            return auth_response.json().get('access_token')
    except:
        pass
    return None

@app.route('/analyze', methods=['POST'])
def analyze():
    token = get_token_from_request()
    
    # If no user token, try to get client credentials token for public playlists
    if not token:
        token = get_client_credentials_token()
        if not token:
            return jsonify({'error': 'Unable to authenticate with Spotify'}), 401
    
    data = request.get_json()
    playlist_url = data.get('playlist_url', '')
    
    try:
        playlist_id = playlist_url.split('playlist/')[-1].split('?')[0]
    except:
        return jsonify({'error': 'Invalid playlist URL'}), 400
    
    headers = {'Authorization': f"Bearer {token}"}
    
    try:
        # Fetch playlist details
        playlist_response = requests.get(f'{SPOTIFY_API_BASE_URL}/playlists/{playlist_id}', headers=headers)
        if playlist_response.status_code != 200:
            error_msg = 'Playlist not found or is private'
            if playlist_response.status_code == 404:
                error_msg = 'Playlist not found. Please check the URL.'
            elif playlist_response.status_code == 403:
                error_msg = 'This playlist is private. Please make it public or login to access it.'
            return jsonify({'error': error_msg}), 400
        
        playlist = playlist_response.json()
        
        # Fetch all tracks (handle pagination)
        all_tracks_data = []
        tracks_url = playlist['tracks']['href']
        
        while tracks_url:
            tracks_response = requests.get(tracks_url, headers=headers)
            if tracks_response.status_code != 200:
                break
            tracks_page = tracks_response.json()
            all_tracks_data.extend(tracks_page.get('items', []))
            tracks_url = tracks_page.get('next')  # Get next page URL
        
        # Extract all track details with album images
        all_tracks = []
        for item in all_tracks_data:
            if item and item.get('track'):
                track = item['track']
                all_tracks.append({
                    'name': track.get('name', 'Unknown'),
                    'artists': ', '.join([a['name'] for a in track.get('artists', [])]),
                    'album_image': track['album']['images'][0]['url'] if track.get('album') and track['album'].get('images') else None,
                    'album_name': track['album'].get('name', 'Unknown') if track.get('album') else 'Unknown',
                    'duration_ms': track.get('duration_ms', 0),
                    'popularity': track.get('popularity', 0)
                })
        
        total_tracks = len(all_tracks_data)
        total_duration_ms = sum(item['track']['duration_ms'] for item in all_tracks_data if item and item.get('track'))
        total_duration_hours = round(total_duration_ms / (1000 * 60 * 60), 2)
        
        popularities = [item['track']['popularity'] for item in all_tracks_data if item and item.get('track')]
        avg_popularity = round(sum(popularities) / len(popularities)) if popularities else 0
        
        most_popular = max(all_tracks_data, key=lambda x: x['track']['popularity'] if x and x.get('track') else 0)
        most_popular_track = most_popular['track']['name'] if most_popular and most_popular.get('track') else 'N/A'
        most_popular_artist = most_popular['track']['artists'][0]['name'] if most_popular and most_popular.get('track') and most_popular['track'].get('artists') else 'N/A'
        
        artist_counts = {}
        for item in all_tracks_data:
            if item and item.get('track') and item['track'].get('artists'):
                artist_name = item['track']['artists'][0]['name']
                artist_counts[artist_name] = artist_counts.get(artist_name, 0) + 1
        
        most_common_artist = max(artist_counts, key=artist_counts.get) if artist_counts else 'N/A'
        artist_count = artist_counts.get(most_common_artist, 0)
        
        # Get playlist cover image
        playlist_image = playlist['images'][0]['url'] if playlist.get('images') else None
        
        return jsonify({
            'playlist_name': playlist.get('name', 'Unknown Playlist'),
            'playlist_owner': playlist['owner'].get('display_name', 'Unknown'),
            'playlist_image': playlist_image,
            'tracks': all_tracks,
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
        return jsonify({'error': f'Failed to analyze playlist: {str(e)}'}), 500

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
                artist_name = t['artists'][0]['name'] if t.get('artists') else 'Unknown'
                user_stats['top_tracks'].append(f"{t.get('name', 'Unknown')} - {artist_name}")
            if tracks:
                top_track = tracks[0]
                personalized_insights.append(f"Your current favorite track is '{top_track.get('name', 'Unknown')}' by {top_track['artists'][0]['name'] if top_track.get('artists') else 'Unknown'}.")
    except Exception as e:
        pass

    return jsonify({
        'user_stats': user_stats,
        'personalized_insights': personalized_insights
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
