#!/bin/bash
# startup.sh — Starts both the Flask API server and Streamlit app

# Start Flask API server in background (port 3000)
echo "[startup] Starting Flask API server on port 3000..."
python api_server.py &
API_PID=$!

# Give Flask a moment to start
sleep 2

# Start Streamlit in background (port 8080)
echo "[startup] Starting Streamlit on port 8080..."
streamlit run app.py --server.address=0.0.0.0 --server.port=8080 &
STREAMLIT_PID=$!

echo "[startup] API PID: $API_PID, Streamlit PID: $STREAMLIT_PID"

# Wait for both processes
wait $API_PID $STREAMLIT_PID
