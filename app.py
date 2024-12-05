import mysql.connector.cursor
import numpy as np 
from flask import Flask , request , jsonify
import joblib
import mysql.connector
from flask_cors import CORS 
import pandas as pd
from sklearn.preprocessing import MinMaxScaler , StandardScaler



app = Flask(__name__)

CORS(app)

# config MySQL
db_config = {
    "host" : "localhost",
    "user" : "root",
    "password" : "" , 
    "database" : "sisrekomact"
}

def load_model():
    return joblib.load('kmeans_model.joblib')

db_connection = mysql.connector.connect(**db_config)


@app.route('/')
def Home():
    return {"status" : "true" , "message" : "Berhasil menjalankan server"}


@app.route('/eda-mahasiswa', methods=['GET'])
def eda_mahasiswa():
    # Fetch data from the database
    query = "SELECT * FROM dataset_mahasiswa"
    data = pd.read_sql(query, db_connection)

    # Clean the data
    data = data.dropna(subset=['ipk_mahasiswa', 'pembimbing_tugas_akhir'])
    data = data.drop_duplicates()

    # Update the cleaned data back into the database
    cursor = db_connection.cursor(dictionary=True)
    for index, row in data.iterrows():
        update_query = """
            UPDATE dataset_mahasiswa
            SET ipk_mahasiswa = %s, pembimbing_tugas_akhir = %s
            WHERE id = %s
        """
        cursor.execute(update_query, (row['ipk_mahasiswa'], row['pembimbing_tugas_akhir'], row['id']))  # Assuming 'id' is the primary key
    db_connection.commit()  # Commit the changes to the database

    # Return the cleaned data as JSON
    return jsonify(data.to_dict(orient='records'))


@app.route('/eda-krs', methods=['GET'])
def eda_krs():
    # Query to fetch data
    query = "SELECT * FROM dataset_krs"
    data = pd.read_sql(query, db_connection)

    # Clean and modify data
    data = data.dropna(subset=['kode_nilai'])
    data = data.drop_duplicates()
    data['kode_nilai'] = data['kode_nilai'].replace('A', 4)
    data['kode_nilai'] = data['kode_nilai'].replace('B', 3)
    data['kode_nilai'] = data['kode_nilai'].replace('C', 2)
    data['kode_nilai'] = data['kode_nilai'].replace('D', 1)
    data['kode_nilai'] = data['kode_nilai'].replace('E', 0)
    data['kode_nilai'].fillna(0, inplace=True)

    # Update the database with modified data
    cursor = db_connection.cursor(dictionary=True)
    for index, row in data.iterrows():
        update_query = """
            UPDATE dataset_krs
            SET kode_nilai = %s
            WHERE id = %s
        """
        cursor.execute(update_query, (row['kode_nilai'], row['id']))  # Assuming 'id' is the primary key
    db_connection.commit()  # Commit the changes to the database

    # Return the modified data as JSON
    return jsonify(data.to_dict(orient='records'))



    

@app.route('/eda-kegiatan' , methods=['GET'])
def eda_kegiatan():
    query = "SELECT * FROM dataset_kegiatanmahasiswa"
    data = pd.read_sql(query , db_connection)
    data = data.dropna()
    data = data.drop_duplicates(inplace=True)

    return jsonify(data.to_dict(orient='records'))

import os
import json

# File to store cached results
CACHE_FILE = "cluster_cache.json"

# Load cache from file on startup
def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as file:
            return json.load(file)
    return {}

# Save cache to file
def save_cache(cache):
    with open(CACHE_FILE, "w") as file:
        json.dump(cache, file)

# Initialize the cache
cluster_cache = load_cache()

@app.route('/rekomendasi', methods=['GET'])
def rata_rata_dan_rekomendasi():
    try:
        npm_mahasiswa = request.args.get('npm_mahasiswa')  # Get npm_mahasiswa from the query parameters

        if not npm_mahasiswa:
            return jsonify({"status": "error", "message": "npm_mahasiswa is required"}), 400

        # Check if the cluster and rata-rata are already cached
        if npm_mahasiswa in cluster_cache:
            cluster = cluster_cache[npm_mahasiswa]['cluster']
            rata_rata = cluster_cache[npm_mahasiswa]['rata_rata']
        else:
            # Use SQL's AVG to calculate the averages directly
            query = """
            SELECT 
                npm_mahasiswa,
                kategori_matakuliah,
                AVG(kode_nilai) AS rata_rata_nilai
            FROM dataset_krs
            GROUP BY npm_mahasiswa, kategori_matakuliah
            """
            # Execute the query and load the data into a DataFrame
            df = pd.read_sql(query, db_connection)

            # Drop duplicate rows
            df = df.drop_duplicates()

            # Pivot the DataFrame to get each category as a column
            pivot_df = df.pivot(
                index="npm_mahasiswa",
                columns="kategori_matakuliah",
                values="rata_rata_nilai"
            ).reset_index()

            # Clean column names
            pivot_df.columns = pivot_df.columns.str.strip()
            pivot_df = pivot_df.loc[:, ~pivot_df.columns.duplicated()]

            # Remove "Tugas Akhir" column if it exists
            if "Tugas Akhir" in pivot_df.columns:
                pivot_df.drop(columns=["Tugas Akhir"], inplace=True)

            # Fill NaN values with 0
            pivot_df.fillna(0, inplace=True)

            # Normalize the data for clustering (excluding 'npm_mahasiswa')
            scaler = MinMaxScaler()
            numeric_columns = pivot_df.columns[1:]  # Exclude 'npm_mahasiswa'
            normalized_data = pivot_df.copy()
            normalized_data[numeric_columns] = scaler.fit_transform(pivot_df[numeric_columns])

            # Apply KMeans clustering
            kmeans = load_model()
            normalized_data['cluster'] = kmeans.fit_predict(normalized_data[numeric_columns])
            pivot_df['cluster'] = normalized_data['cluster']

            # Cache the cluster and rata-rata for all students
            for _, row in pivot_df.iterrows():
                rata_rata = {col: row[col] for col in numeric_columns}
                cluster_cache[row['npm_mahasiswa']] = {
                    "cluster": int(row['cluster']),
                    "rata_rata": rata_rata
                }

            # Save the updated cache to a file
            save_cache(cluster_cache)

            # Get the cluster and rata-rata for the specific student
            if npm_mahasiswa not in cluster_cache:
                return jsonify({"status": "error", "message": "Student not found"}), 404

            cluster = cluster_cache[npm_mahasiswa]['cluster']
            rata_rata = cluster_cache[npm_mahasiswa]['rata_rata']

        # Map the cluster to categories
        cluster_mapping = {
            0: "DKV",  # Cluster 0 is for UMUM
            1: "PSI",   # Cluster 1 is for PSI
            2: "Umum"    # Cluster 2 is for DKV
        }
        category = cluster_mapping.get(cluster, "Unknown")

        # Fetch activities from the database based on the student's cluster category
        query_activities = """
        SELECT nama_kegiatan, kategori
        FROM dataset_kegiatanmahasiswa
        WHERE kategori = %s LIMIT 12
        """
        activities_df = pd.read_sql(query_activities, db_connection, params=[category])

        if activities_df.empty:
            return jsonify({
                "status": "error",
                "message": f"No activities found for category {category}"
            }), 404

        # Convert activities into a list
        recommended_activities = activities_df['nama_kegiatan'].tolist()

        return jsonify({
            "status": "success",
            "npm_mahasiswa": npm_mahasiswa,
            "cluster": cluster,
            "category": category,
            "rata_rata": rata_rata,
            "recommended_activities": recommended_activities
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        })





if __name__ == '__main__':
    app.run(debug=True)