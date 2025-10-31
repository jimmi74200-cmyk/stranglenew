import flask
from flask import request, Response, render_template, url_for
import logging
import io
import csv
from py5paisa import FivePaisaClient
import json
import os
import sys

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration Handling ---
try:
    import config
except ImportError:
    logging.critical("ERROR: config.py not found. Please create it by copying config.py.example and filling in your credentials.")
    sys.exit(1)

# Initialize Flask app
app = flask.Flask(__name__, template_folder='templates')

# No longer need to initialize the client as we are using direct API calls.

# --- Scrip Data Handling ---
SCRIP_DATA_PATH = os.path.join(os.path.dirname(__file__), 'scrip_data.json')
scrip_data = None

def load_scrip_data():
    """Loads the scrip data JSON file."""
    global scrip_data
    try:
        with open(SCRIP_DATA_PATH, 'r') as f:
            scrip_data = json.load(f)
        logging.info("Scrip data loaded successfully.")
    except FileNotFoundError:
        logging.error(f"Error: {SCRIP_DATA_PATH} not found.")
    except Exception as e:
        logging.error(f"Error loading scrip data: {e}")

import requests

# --- Helper Function ---
def fetch_historical_data(symbol, interval, from_date, to_date):
    """
    A helper function to fetch data directly from the API using requests.
    """
    instrument = scrip_data.get(symbol)
    if not instrument:
        raise ValueError(f"Could not find scrip details for symbol: {symbol}")

    scrip_code = instrument.get('ScripCode')
    exch = instrument.get('Exch')
    exch_type = instrument.get('ExchType')

    logging.info(f"Fetching data for {symbol} ({scrip_code}) from {from_date} to {to_date} via direct API call.")

    base_url = "https://openapi.5paisa.com/V2/historical"
    url = f"{base_url}/{exch}/{exch_type}/{scrip_code}/{interval}?from={from_date}&end={to_date}"

    headers = {
        "Authorization": f"Bearer {config.ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)

        data = response.json()

        if data.get("status") == "success" and "data" in data and "candles" in data["data"]:
            # The API returns a list of lists. We need to convert it to a list of dicts for the template.
            candles = data["data"]["candles"]
            # The order of fields is Timestamp, Open, High, Low, Close, Volume
            dict_list = [
                {
                    "Datetime": c[0],
                    "Open": c[1],
                    "High": c[2],
                    "Low": c[3],
                    "Close": c[4],
                    "Volume": c[5]
                } for c in candles
            ]
            return dict_list
        else:
            # Handle API-level errors reported in a 200 OK response
            error_message = data.get("head", {}).get("Status_description", "Unknown API error.")
            logging.error(f"API returned an error: {error_message} | Full response: {data}")
            raise ConnectionError(error_message)

    except requests.exceptions.RequestException as e:
        logging.error(f"An error occurred with the request: {e}")
        raise ConnectionError(f"A network error occurred: {e}")
    except json.JSONDecodeError:
        logging.error("Failed to decode JSON from response. Raw response: " + response.text)
        raise ValueError("The server returned an invalid response.")

# --- Flask Routes ---
@app.route('/')
def index():
    """Renders the main data downloader page."""
    return render_template('data_downloader.html', symbols=list(scrip_data.keys()) if scrip_data else [])

@app.route('/view_data', methods=['POST'])
def view_data():
    """Fetches data and displays it on the page."""
    form_data = {
        'symbol': request.form.get('symbol', '').upper(),
        'interval': request.form.get('interval', '1d'),
        'from_date': request.form.get('from_date'),
        'to_date': request.form.get('to_date')
    }

    if not all(form_data.values()):
        return "Missing form parameters.", 400

    try:
        data = fetch_historical_data(**form_data)
        if not isinstance(data, list) or not data:
            message = f"No data returned from API for {form_data['symbol']}. This is the raw response from the server:"
            logging.warning(f"Raw API Response: {data}")
            return render_template('data_downloader.html', symbols=list(scrip_data.keys()), form_data=form_data, message=message, raw_response=data)

        # Pass data and form selections back to the template
        return render_template('data_downloader.html', symbols=list(scrip_data.keys()), data=data, form_data=form_data)

    except Exception as e:
        logging.error(f"Error fetching or processing data: {e}")
        return render_template('data_downloader.html', symbols=list(scrip_data.keys()), form_data=form_data, message=f"An error occurred: {e}")

@app.route('/download_csv')
def download_csv():
    """Handles the data download request as a CSV file."""
    # Get parameters from URL
    params = {
        'symbol': request.args.get('symbol'),
        'interval': request.args.get('interval'),
        'from_date': request.args.get('from_date'),
        'to_date': request.args.get('to_date')
    }

    if not all(params.values()):
        return "Missing URL parameters for download.", 400

    try:
        data = fetch_historical_data(**params)
        if not isinstance(data, list) or not data:
            return f"No data returned from API for {params['symbol']}.", 404

        # Convert to CSV
        output = io.StringIO()
        fieldnames = sorted(data[0].keys(), key=lambda x: (x != 'Datetime', x))
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)

        # Create response
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename={params['symbol']}_{params['from_date']}_{params['to_date']}.csv"}
        )

    except Exception as e:
        logging.error(f"Error creating CSV file: {e}")
        return f"An error occurred while generating the CSV: {e}", 500


if __name__ == '__main__':
    load_scrip_data()
    if not scrip_data:
        sys.exit(1)
    app.run(debug=True, port=5002)