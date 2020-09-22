import json
import os
import time
import uuid
from operator import and_

import requests
from flask import Flask, render_template, abort
from flask_basicauth import BasicAuth
from flask_cors import CORS
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import desc, asc
from sqlalchemy.dialects.postgresql import DATE, UUID
from walrus import Database

from config import Config

app = Flask(__name__)
app.config.from_object(Config)
db = SQLAlchemy(app)
migrate = Migrate(app, db)
CORS(app)
basic_auth = BasicAuth(app)

redis_db = Database(host=os.environ.get('CACHE_REDIS_HOST'), port=os.environ.get('CACHE_REDIS_PORT'),
                    db=os.environ.get('CACHE_REDIS_DB'), password=os.environ.get('CACHE_REDIS_PASSWORD'))
cache = redis_db.cache()

DATA_DIR = app.config['DATA_DIR']


class Records(db.Model):
    __tablename__ = 'records'
    __table_args__ = {'extend_existing': True}

    uuid = db.Column(UUID(as_uuid=True), primary_key=True)
    country_iso = db.Column(db.String(100), index=True)
    country_name = db.Column(db.String(100))
    date = db.Column(DATE)
    confirmed = db.Column(db.INTEGER)
    deaths = db.Column(db.INTEGER)
    recovered = db.Column(db.INTEGER)

    def __repr__(self):
        return f'<Record ID: {self.uuid}, ISO: {self.country_iso}, Country: {self.country_name}, Date: {self.date}, {self.confirmed, self.deaths, self.deaths}>'


@app.route('/')
@cache.cached(timeout=86400, metrics=True)
def home():
    return render_template('index.html')


@app.route('/api/v1/country/<country_iso>')
@cache.cached(timeout=86400, metrics=True)
def country(country_iso):
    result = Records.query.filter_by(country_iso=country_iso.upper()).all()
    if len(result) == 0:
        abort(404)
    data = {
        'count': len(result),
        'result': {}
    }
    for record in result:
        data['result'][record.date.strftime('%Y-%m-%d')] = {"confirmed": record.confirmed, "deaths": record.deaths,
                                                            "recovered": record.recovered}
    return data


@app.route('/api/v1/country/<country_iso>/<date>')
@cache.cached(timeout=86400, metrics=True)
def country_date(country_iso, date):
    result = fetch_country_on_date(country_iso.upper(), date)
    data = {
        'count': 1,
        'result': {}
    }
    data['result'][result.date.strftime('%Y-%m-%d')] = {"confirmed": result.confirmed, "deaths": result.deaths,
                                                        "recovered": result.recovered}
    return data


@app.route('/api/v1/country/<country_iso>/timeseries/<from_date>/<to_date>')
@cache.cached(timeout=86400, metrics=True)
def country_timeseries(country_iso, from_date, to_date):
    results = Records.query.filter(Records.country_iso == country_iso).filter(
        and_(Records.date >= from_date, Records.date < to_date)).order_by(asc(Records.date)).all()
    if len(results) == 0:
        abort(404)
    data_list = []
    for result in results:
        data_list.append({"date": str(result.date), "confirmed": result.confirmed, "deaths": result.deaths,
                          "recovered": result.recovered})
    data = {
        'count': len(results),
        'result': data_list
    }
    return data


@cache.cached(timeout=86400, metrics=True)
def get_country_time_series(country_iso, from_date, to_date):
    result = Records.query.filter(Records.country_iso == country_iso).filter(
        and_(Records.date >= from_date, Records.date < to_date)).order_by(asc(Records.date)).all()
    return result


@app.route('/api/v1/global/timeseries/<from_date>/<to_date>')
@cache.cached(timeout=86400, metrics=True)
def global_timeseries(from_date, to_date):
    result = {}
    country_list = Records.query.distinct(Records.country_iso).all()
    data = {
        'count': len(country_list),
        'result': result
    }

    for country in country_list:
        country_result = get_country_time_series(country.country_iso, from_date, to_date)
        data_list = []
        for entry in country_result:
            data_list.append({"date": str(entry.date), "confirmed": entry.confirmed, "deaths": entry.deaths,
                              "recovered": entry.recovered})
        result[country.country_iso] = data_list
    return data


@cache.cached(timeout=86400, metrics=True)
def fetch_country_on_date(country_iso, date):
    result = Records.query.filter(Records.country_iso == country_iso).filter(Records.date == date).first()
    if not result:
        abort(404)
    else:
        return result


@app.route('/api/v1/global')
@cache.cached(timeout=86400, metrics=True)
def world():
    date = Records.query.filter(Records.country_iso == "IND").order_by(desc(Records.date)).first().date
    results = Records.query.filter(Records.date == date).all()
    global_confirmed_count, global_death_count, global_recovered_count = 0, 0, 0
    for result in results:
        global_confirmed_count += result.confirmed
        global_death_count += result.deaths
        global_recovered_count += result.recovered
    data = {
        'count': 1,
        'date': str(date),
        'result': {"confirmed": global_confirmed_count, "deaths": global_death_count,
                   "recovered": global_recovered_count}
    }
    return data


@app.route('/api/v1/global/<date>')
@cache.cached(timeout=86400, metrics=True)
def world_date(date):
    results = Records.query.filter(Records.date == date).all()
    global_confirmed_count, global_death_count, global_recovered_count = 0, 0, 0
    for result in results:
        global_confirmed_count += result.confirmed
        global_death_count += result.deaths
        global_recovered_count += result.recovered
    data = {
        'count': 1,
        'date': date,
        'result': {"confirmed": global_confirmed_count, "deaths": global_death_count,
                   "recovered": global_recovered_count}
    }
    return data


@app.route('/api/v1/global/<from_date>/<to_date>')
@cache.cached(timeout=86400, metrics=True)
def world_date_window(from_date, to_date):
    from_date_result = Records.query.filter(Records.date == from_date).all()
    to_date_result = Records.query.filter(Records.date == to_date).all()
    from_date_confirmed_count, from_date_death_count, from_date_recovered_count = 0, 0, 0
    to_date_confirmed_count, to_date_death_count, to_date_recovered_count = 0, 0, 0

    for result in from_date_result:
        from_date_confirmed_count += result.confirmed
        from_date_death_count += result.deaths
        from_date_recovered_count += result.recovered

    for result in to_date_result:
        to_date_confirmed_count += result.confirmed
        to_date_death_count += result.deaths
        to_date_recovered_count += result.recovered

    data = {
        'count': 1,
        'from_date': from_date,
        'to_date': to_date,
        'result': {
            "confirmed": abs(from_date_confirmed_count - to_date_confirmed_count),
            "deaths": abs(from_date_death_count - to_date_death_count),
            "recovered": abs(from_date_recovered_count - to_date_recovered_count)}
    }
    return data


@app.route('/api/v1/latest-date')
@cache.cached(timeout=86400, metrics=True)
def latest_date():
    latest_date = Records.query.filter(Records.country_iso == "IND").order_by(desc(Records.date)).first().date
    return str(latest_date)


@app.route('/api/v1/country/<country_iso>/latest')
@cache.cached(timeout=86400, metrics=True)
def country_latest(country_iso):
    latest_date = Records.query.filter(Records.country_iso == "IND").order_by(desc(Records.date)).first().date
    result = fetch_country_on_date(country_iso, latest_date)
    data = {
        'count': 1,
        'result': {}
    }
    data['result'][result.date.strftime('%Y-%m-%d')] = {"confirmed": result.confirmed, "deaths": result.deaths,
                                                        "recovered": result.recovered}
    return data


@cache.cached(timeout=86400, metrics=True)
def global_count_on_date(date):
    dates = Records.query.filter(Records.date == date).all()
    latest_date = Records.query.filter(Records.country_iso == "IND").order_by(desc(Records.date)).first().date
    print(dates)
    return dates


@cache.cached(timeout=86400, metrics=True)
@app.route('/api/v1/global/count')
def global_count():
    dates = Records.query.distinct(Records.date).all()
    date_result = {}
    for entry in dates:
        date = entry.date
        results = global_count_on_date(date)
        global_confirmed_count, global_death_count, global_recovered_count = 0, 0, 0
        for result in results:
            global_confirmed_count += result.confirmed
            global_death_count += result.deaths
            global_recovered_count += result.recovered
        date_result[str(date)] = {
            "confirmed": global_confirmed_count,
            "deaths": global_death_count,
            "recovered": global_recovered_count
        }
    data = {
        "count": len(date_result),
        "result": date_result
    }
    return data


@cache.cached(timeout=86400, metrics=True)
@app.route('/api/v1/global/latest')
def global_latest():
    latest_date = Records.query.filter(Records.country_iso == "IND").order_by(desc(Records.date)).first().date
    results = global_count_on_date(latest_date)
    data = {
        'count': len(results),
        'result': [],
        'date': str(latest_date)
    }
    for result in results:
        country_data = {}
        country_data[result.country_iso] = {"confirmed": result.confirmed, "deaths": result.deaths,
                                            "recovered": result.recovered}
        data['result'].append(country_data)
    return data


def update_db():
    t1 = time.time()
    record_counter = 0
    # Fetch the latest dataset
    master_data_url = "https://pomber.github.io/covid19/timeseries.json"
    country_name_to_iso_file = DATA_DIR + '/country_name_to_iso.json'
    master_data_json = requests.get(master_data_url).json()
    countries = list(master_data_json.keys())

    with open(country_name_to_iso_file, 'r') as fp:
        country_name_to_code = json.loads(fp.read())

    db.session.query(Records).delete()
    db.session.commit()

    for country in countries:
        country_records = []
        for everyday in master_data_json[country]:
            everyday_record = {
                "uuid": uuid.uuid4(),
                "country_name": country,
                "country_iso": country_name_to_code.get(country),
                "date": everyday["date"],
                "confirmed": everyday["confirmed"],
                "deaths": everyday["deaths"],
                "recovered": everyday["recovered"] or 0,
            }
            country_records.append(everyday_record)

        db.session.bulk_insert_mappings(Records, country_records)
        db.session.commit()
        print(f"Added record for {country}")
        record_counter += len(country_records)

    redis_db.flushdb()
    print(f"Added records for {len(countries)} countries!")
    return f"Added {record_counter} records in {time.time() - t1} seconds!"


@app.route('/protected/clear-redis')
@basic_auth.required
def clear_redis():
    redis_db.flushdb()
    return "Cleared Redis!!!"


@app.route('/protected/redis-info')
@basic_auth.required
def redis_info():
    info = redis_db.info()
    data = {
        "memory": info.get("used_memory_human"),
        "db": info.get(f"db{os.environ.get('CACHE_REDIS_DB')}"),
        "commands_processed": info.get("total_commands_processed"),
        "keyspace_hits": info.get("keyspace_hits"),
        "keyspace_misses": info.get("keyspace_misses")
    }
    return data
