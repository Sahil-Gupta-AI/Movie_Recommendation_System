import streamlit as st
import pickle
import requests
import pandas as pd
from difflib import get_close_matches
from math import ceil
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.parse
import logging
import time

# ========== Logging Setup ==========
logging.basicConfig(level=logging.CRITICAL)  # Only show CRITICAL errors (almost never)
logger = logging.getLogger(__name__)

# ========== Load Data ==========
movies_dict = pickle.load(open("movies.pkl", "rb"))
movies = pd.DataFrame(movies_dict)
similarity = pickle.load(open("similarity.pkl", "rb"))

# ========== TMDb API Key ==========
api_key = st.secrets["TMDB_API_KEY"]

# ========== Fetch Movie Details with Retry & Delay ==========
@st.cache_data(show_spinner=False)
def fetch_movie_details(title, retries=3, delay=2):
    for attempt in range(retries):
        try:
            url = "https://api.themoviedb.org/3/search/movie"
            params = {"api_key": api_key, "query": title}
            headers = {"User-Agent": "Mozilla/5.0"}
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            results = response.json().get("results")

            if not results:
                logger.warning(f"[TMDb] No result for: {title}")
                return {
                    "title": title,
                    "poster": "https://via.placeholder.com/450x650?text=No+Poster",
                    "year": "Unknown",
                    "rating": "N/A",
                    "overview": ""
                }

            movie = results[0]
            poster_path = movie.get("poster_path")
            poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else "https://via.placeholder.com/450x650?text=No+Poster"
            release_date = movie.get("release_date", "Unknown")
            year = release_date.split("-")[0] if release_date else "Unknown"
            rating = movie.get("vote_average", "N/A")
            overview = movie.get("overview", "")

            return {
                "title": movie.get("title", title),
                "poster": poster_url,
                "year": year,
                "rating": rating,
                "overview": overview
            }

        except Exception as e:
            logger.error(f"[ERROR] Attempt {attempt + 1} - Failed to fetch '{title}': {e}")
            time.sleep(delay)

    return {
        "title": title,
        "poster": "https://via.placeholder.com/450x650?text=No+Poster",
        "year": "Unknown",
        "rating": "N/A",
        "overview": ""
    }

# ========== Fetch Trending Movies Once ==========
@st.cache_data(show_spinner=False)
def fetch_trending_movies_once():
    try:
        url = "https://api.themoviedb.org/3/trending/movie/week"
        params = {"api_key": api_key}
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        results = response.json().get("results", [])
        trending = []
        for movie in results:  # fetch all results
            poster_path = movie.get("poster_path")
            poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else "https://via.placeholder.com/450x650?text=No+Poster"
            release_date = movie.get("release_date", "Unknown")
            year = release_date.split("-")[0] if release_date else "Unknown"
            rating = movie.get("vote_average", "N/A")
            overview = movie.get("overview", "")
            trending.append({
                "title": movie.get("title", "Unknown"),
                "poster": poster_url,
                "year": year,
                "rating": rating,
                "overview": overview
            })
        return trending
    except Exception as e:
        logger.error(f"[ERROR] Failed to fetch trending movies: {e}")
        return []

if "trending_movies" not in st.session_state:
    st.session_state["trending_movies"] = fetch_trending_movies_once()

# ========== YouTube-like Search & Recommend ==========
def youtube_like_search(query):
    all_titles = movies['title'].tolist()
    matches = get_close_matches(query, all_titles, n=1, cutoff=0.5)
    if matches:
        return matches[0]
    return None

def recommend(movie_query):
    movie = youtube_like_search(movie_query)
    if not movie:
        return []
    try:
        movie_index = movies[movies["title"].str.lower() == movie.lower()].index[0]
    except IndexError:
        return []

    distances = similarity[movie_index]
    movie_list = sorted(list(enumerate(distances)), reverse=True, key=lambda x: x[1])[1:50]
    titles = [movies.iloc[i[0]].title for i in movie_list]
    return titles

# ========== Streamlit UI ==========
st.set_page_config(page_title="🎬 Movie Recommender", layout="wide")
st.title("🎬 Movie Recommendation System")
st.write("Find movies similar to your favorite one, and check out what’s trending now!")

movie_name = st.text_input("🔍 Enter a movie name:", "").strip()

st.markdown("""
<style>
/* Grid layout spacing */
.stColumns {
    gap: 16px !important; /* small margin between boxes */
}

/* Movie Card */
.movie-card {
    text-align: center;
    padding: 6px;  /* reduced padding = bigger poster */
    border-radius: 16px;
    background: rgba(38, 38, 38, 0.65);
    backdrop-filter: blur(10px);
    box-shadow: 0 6px 16px rgba(0,0,0,0.45);
    transition: all 0.3s ease-in-out;
    margin-bottom: 24px;
    width: 285px;   /* fixed width */
    height: 520px;  /* fixed height */
    cursor: pointer;
    position: relative;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
}
.movie-card:hover {
    transform: translateY(-6px) scale(1.05);
    box-shadow: 0px 14px 30px rgba(0,0,0,0.75);
     height: 522px;
}

/* Poster */
.movie-card img {
    border-radius: 14px;
    width: 100%;
    height: 443px;   /* larger poster area */
    object-fit: cover;
    transition: transform 0.4s ease;
}
.movie-card:hover img {
    transform: scale(1.08); /* zoom poster slightly */
}

/* Floating Badge (rating/year) - only on hover */
.movie-badge {
    position: absolute;
    bottom: 12px;
    right: 12px;
    background: linear-gradient(135deg,#ff512f,#dd2476);
    color: #fff;
    font-weight: 600;
    font-size: 12px;
    padding: 5px 9px;
    border-radius: 10px;
    box-shadow: 0 4px 10px rgba(0,0,0,0.35);
    opacity: 0;
    transform: translateY(8px);
    transition: all 0.25s ease-in-out;
}
.movie-card:hover .movie-badge {
    opacity: 1;
    transform: translateY(0);
}

/* Movie Title */
.movie-title {
    font-weight: 700;
    font-size: 15px;
    margin-top: 10.5px;
    color: #f5f5f5;
    text-overflow: ellipsis;
    overflow: hidden;
    white-space: nowrap;
}
.movie-card:hover .movie-title {
   margin-top: 18.5px;
}

/* Skeleton Loader */
.skeleton-card {
   height: 520px;   /* a bit smaller than 535px */
    width: 270px;    /* a bit smaller than 285px */
    background: linear-gradient(-90deg, #2c2c2c 0%, #3a3a3a 50%, #2c2c2c 100%);
    background-size: 400% 400%;
    border-radius: 14px;
    margin-bottom: 24px;
    animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse {
    0% {background-position: 100% 50%;}
    100% {background-position: 0% 50%;}
}
</style>


""", unsafe_allow_html=True)

# ========== Pagination helpers ==========
PAGE_SIZE = 15
if "pages" not in st.session_state:
    st.session_state.pages = {"trending": 0, "recommend": 0}

def go_prev(prefix: str):
    st.session_state.pages[prefix] = max(0, st.session_state.pages.get(prefix, 0) - 1)

def go_next(prefix: str, titles_len: int):
    max_page = max(0, ceil(titles_len / PAGE_SIZE) - 1)
    st.session_state.pages[prefix] = min(st.session_state.pages.get(prefix, 0) + 1, max_page)

def display_movies_paginated(titles, key_prefix="default"):
    # ensure page entry exists
    if key_prefix not in st.session_state.pages:
        st.session_state.pages[key_prefix] = 0

    page = st.session_state.pages[key_prefix]
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    current_titles = titles[start:end]

    if not current_titles:
        st.info("✅ No more movies to display.")
        return

    # Layout: 5 movies per row, mini-batches with skeletons
    batch_size = 5
    total = len(current_titles)
    total_batches = ceil(total / batch_size)
    loading_text = st.empty()

    for batch in range(total_batches):
        loading_text.text(f"Loading page {page+1}, batch {batch+1} of {total_batches}...")
        row_start = batch * batch_size
        row_end = min(row_start + batch_size, total)
        cols = st.columns(batch_size)
        placeholders = [col.empty() for col in cols[:row_end - row_start]]

        # skeletons
        for ph in placeholders:
            ph.markdown('<div class="skeleton-card"></div>', unsafe_allow_html=True)

        # fetch concurrently
        with ThreadPoolExecutor(max_workers=batch_size) as executor:
            futures = {
                executor.submit(fetch_movie_details, current_titles[i]): i
                for i in range(row_start, row_end)
            }
            for future in as_completed(futures):
                idx = futures[future] - row_start
                movie = future.result()
                search_url = "https://www.google.com/search?q=" + urllib.parse.quote(movie['title'])
                placeholders[idx].markdown(f"""
                    <a href="{search_url}" target="_blank" style="text-decoration:none;">
                        <div class="movie-card loaded">
                            <img src="{movie['poster']}">
                            <div class="movie-title">{movie['title']}</div>
                            <div class="movie-info">({movie['year']}) ⭐ {movie['rating']}</div>
                        </div>
                    </a>
                """, unsafe_allow_html=True)

        time.sleep(0.2)

    loading_text.empty()
    st.markdown("<div class='row-margin'></div>", unsafe_allow_html=True)

    # --- Navigation Controls (use on_click callbacks) ---
    total_pages = ceil(len(titles) / PAGE_SIZE)
    col1, col2, col3 = st.columns([1, 2, 1])

    with col1:
        if page > 0:
            st.button("⬅️ Previous", key=f"prev_{key_prefix}", on_click=go_prev, args=(key_prefix,))

    with col2:
        st.markdown(f"<div class='page-indicator'>📄 Page {page+1} of {total_pages}</div>", unsafe_allow_html=True)

    with col3:
        if end < len(titles):
            st.button("Next ➡️", key=f"next_{key_prefix}", on_click=go_next, args=(key_prefix, len(titles)))

# ========== Recommended Movies ==========
# reset recommendation page when the search term changes (so user always starts on page 1 for a new search)
if movie_name:
    if st.session_state.get("last_query") != movie_name:
        st.session_state.pages["recommend"] = 0
        st.session_state["last_query"] = movie_name

    titles = recommend(movie_name)
    if titles:
        st.subheader("✨ Recommended Movies")
        display_movies_paginated(titles, key_prefix="recommend")
    else:
        st.error("❌ Movie not found in the database. Please try another.")

# ========== Trending Movies ==========
st.subheader("🔥 Trending This Week")
display_movies_paginated([m['title'] for m in st.session_state["trending_movies"]], key_prefix="trending")
