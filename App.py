from flask import Flask, redirect, request, jsonify
from flask_cors import CORS
import requests
import urllib.parse
import secrets
import os
from collections import Counter

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
            
            # Use HTML redirect for iOS compatibility (prevents opening Spotify app)
            return f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Redirecting...</title>
                <style>
                    body {{
                        margin: 0; padding: 0; display: flex; align-items: center; justify-content: center;
                        min-height: 100vh; background: #000; color: #1DB954;
                        font-family: -apple-system, BlinkMacSystemFont, 'Inter', sans-serif; font-size: 20px;
                    }}
                    .spinner {{
                        width: 40px; height: 40px; margin: 0 auto 20px;
                        border: 4px solid rgba(29, 185, 84, 0.2);
                        border-top-color: #1DB954;
                        border-radius: 50%;
                        animation: spin 1s linear infinite;
                    }}
                    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
                </style>
            </head>
            <body>
                <div>
                    <div class="spinner"></div>
                    <div>Redirecting back to app...</div>
                </div>
                <script>
                    // Use replace to prevent back button issues
                    window.location.replace("{FRONTEND_URL}?access_token={access_token}");
                </script>
            </body>
            </html>
            """
            
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
        # Get playlist details
        playlist_response = requests.get(f'{SPOTIFY_API_BASE_URL}/playlists/{playlist_id}', headers=headers)
        if playlist_response.status_code != 200:
            return jsonify({'error': 'Failed to fetch playlist'}), 400
        
        playlist = playlist_response.json()
        
        # Get all tracks
        tracks_data = []
        next_url = playlist['tracks']['href']
        while next_url:
            tracks_response = requests.get(next_url, headers=headers)
            tracks_page = tracks_response.json()
            tracks_data.extend(tracks_page.get('items', []))
            next_url = tracks_page.get('next')
        
        # Basic stats
        total_tracks = len(tracks_data)
        total_duration_ms = sum(item['track']['duration_ms'] for item in tracks_data if item['track'])
        total_duration_hours = round(total_duration_ms / (1000 * 60 * 60), 2)
        
        # Popularity stats
        popularities = [item['track']['popularity'] for item in tracks_data if item['track']]
        avg_popularity = round(sum(popularities) / len(popularities)) if popularities else 0
        
        # Most popular track
        most_popular = max(tracks_data, key=lambda x: x['track']['popularity'] if x['track'] else 0)
        most_popular_track = most_popular['track']['name'] if most_popular['track'] else 'N/A'
        most_popular_artist = most_popular['track']['artists'][0]['name'] if most_popular['track'] and most_popular['track']['artists'] else 'N/A'
        most_popular_popularity = most_popular['track']['popularity'] if most_popular['track'] else 0
        
        # Artist analysis
        artist_counts = {}
        all_artists = []
        for item in tracks_data:
            if item['track'] and item['track']['artists']:
                artist_name = item['track']['artists'][0]['name']
                artist_counts[artist_name] = artist_counts.get(artist_name, 0) + 1
                all_artists.append(artist_name)
        
        most_common_artist = max(artist_counts, key=artist_counts.get) if artist_counts else 'N/A'
        artist_count = artist_counts.get(most_common_artist, 0)
        unique_artists = len(artist_counts)
        
        # Top 5 artists
        top_artists = sorted(artist_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        # Album covers (first 16 unique albums)
        album_covers = []
        seen_albums = set()
        for item in tracks_data:
            if item['track'] and item['track']['album']:
                album_id = item['track']['album']['id']
                if album_id not in seen_albums and item['track']['album'].get('images'):
                    album_covers.append(item['track']['album']['images'][0]['url'])
                    seen_albums.add(album_id)
                    if len(album_covers) >= 16:
                        break
        
        # Release year distribution
        release_years = []
        for item in tracks_data:
            if item['track'] and item['track']['album']:
                release_date = item['track']['album'].get('release_date', '')
                if release_date:
                    year = release_date.split('-')[0]
                    if year.isdigit():
                        release_years.append(int(year))
        
        # Get decade distribution
        decade_counts = {}
        for year in release_years:
            decade = (year // 10) * 10
            decade_counts[decade] = decade_counts.get(decade, 0) + 1
        
        oldest_year = min(release_years) if release_years else None
        newest_year = max(release_years) if release_years else None
        
        # Get audio features for first 50 tracks (API limit)
        track_ids = [item['track']['id'] for item in tracks_data[:50] if item['track'] and item['track']['id']]
        audio_features = []
        
        if track_ids:
            # Batch request in groups of 50
            for i in range(0, len(track_ids), 50):
                batch_ids = track_ids[i:i+50]
                features_response = requests.get(
                    f'{SPOTIFY_API_BASE_URL}/audio-features',
                    headers=headers,
                    params={'ids': ','.join(batch_ids)}
                )
                if features_response.status_code == 200:
                    audio_features.extend(features_response.json().get('audio_features', []))
        
        # Calculate average audio features
        avg_energy = 0
        avg_danceability = 0
        avg_valence = 0
        avg_tempo = 0
        
        valid_features = [f for f in audio_features if f]
        if valid_features:
            avg_energy = round(sum(f['energy'] for f in valid_features) / len(valid_features) * 100)
            avg_danceability = round(sum(f['danceability'] for f in valid_features) / len(valid_features) * 100)
            avg_valence = round(sum(f['valence'] for f in valid_features) / len(valid_features) * 100)
            avg_tempo = round(sum(f['tempo'] for f in valid_features) / len(valid_features))
        
        # Explicit content count
        explicit_count = sum(1 for item in tracks_data if item['track'] and item['track'].get('explicit'))
        explicit_percentage = round((explicit_count / total_tracks) * 100) if total_tracks > 0 else 0
        
        return jsonify({
            'playlist_name': playlist['name'],
            'playlist_owner': playlist['owner']['display_name'],
            'playlist_description': playlist.get('description', ''),
            'playlist_image': playlist['images'][0]['url'] if playlist.get('images') else None,
            'album_covers': album_covers,
            'stats': {
                'total_tracks': total_tracks,
                'avg_popularity': avg_popularity,
                'total_duration_hours': total_duration_hours,
                'unique_artists': unique_artists,
                'explicit_percentage': explicit_percentage,
                'oldest_year': oldest_year,
                'newest_year': newest_year,
                'most_popular_track': most_popular_track,
                'most_popular_artist': most_popular_artist,
                'most_popular_popularity': most_popular_popularity,
                'most_common_artist': most_common_artist,
                'artist_count': artist_count,
                'top_artists': [{'name': name, 'count': count} for name, count in top_artists],
                'decade_distribution': [{'decade': f"{d}s", 'count': c} for d, c in sorted(decade_counts.items())],
                'audio_features': {
                    'energy': avg_energy,
                    'danceability': avg_danceability,
                    'valence': avg_valence,
                    'tempo': avg_tempo
                }
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
        'top_genres': [],
        'artist_images': []
    }
    personalized_insights = []

    try:
        # Get top artists with images
        response_artists = requests.get('https://api.spotify.com/v1/me/top/artists?limit=10', headers=headers)
        if response_artists.status_code == 200:
            items = response_artists.json().get('items', [])
            genre_counter = {}
            
            for artist in items:
                user_stats['top_artists'].append(artist['name'])
                # Get artist image
                if artist.get('images'):
                    user_stats['artist_images'].append(artist['images'][0]['url'])
                
                for genre in artist.get('genres', []):
                    genre_counter[genre] = genre_counter.get(genre, 0) + 1
            
            sorted_genres = sorted(genre_counter.items(), key=lambda x: x[1], reverse=True)[:8]
            user_stats['top_genres'] = [{'name': g, 'count': c} for g, c in sorted_genres]
            
            if user_stats['top_artists']:
                personalized_insights.append(f"Your most played artist is {user_stats['top_artists'][0]}! You have excellent taste in music.")
            
            if len(set(g for g, _ in sorted_genres)) >= 3:
                top3 = [g for g, _ in sorted_genres[:3]]
                personalized_insights.append(f"You're into diverse music - your top genres are {', '.join(top3)}.")
            elif sorted_genres:
                personalized_insights.append(f"You're really into {sorted_genres[0][0]} music!")

        # Get top tracks with album covers
        response_tracks = requests.get('https://api.spotify.com/v1/me/top/tracks?limit=10', headers=headers)
        if response_tracks.status_code == 200:
            tracks = response_tracks.json().get('items', [])
            for t in tracks:
                artist_name = t['artists'][0]['name'] if t['artists'] else 'Unknown'
                album_cover = t['album']['images'][0]['url'] if t.get('album', {}).get('images') else None
                user_stats['top_tracks'].append({
                    'name': t['name'],
                    'artist': artist_name,
                    'album_cover': album_cover
                })
            
            if tracks:
                top_track = tracks[0]
                personalized_insights.append(f"Your current favorite track is '{top_track['name']}' by {top_track['artists'][0]['name']}.")
                
            # Audio features insight
            if len(tracks) >= 5:
                personalized_insights.append(f"You have {len(tracks)} tracks in your top 10. Your music taste is well-defined!")

    except Exception as e:
        pass

    return jsonify({
        'user_stats': user_stats,
        'personalized_insights': personalized_insights
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
