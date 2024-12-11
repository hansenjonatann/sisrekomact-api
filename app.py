from flask import Flask, request, jsonify, session
from flask_cors import CORS
import pandas as pd
import os
import datetime
import json
import joblib
from sklearn.preprocessing import MinMaxScaler
import jwt
import mysql.connector

app = Flask(__name__)
CORS(app )

# Secret key untuk sesi
app.config['SECRET_KEY'] = 'sisrekomact-backend-secure-key#2024'

# Konfigurasi database
db_config = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "sisrekomact"
}
db_connection = mysql.connector.connect(**db_config)

# Load KMeans model
def load_model():
    return joblib.load('kmeans_model.joblib')

# Load cache dari file
CACHE_FILE = "cluster_cache.json"

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as file:
            return json.load(file)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "w") as file:
        json.dump(cache, file)

cluster_cache = load_cache()

@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.json
        npm_mahasiswa = data.get('npm_mahasiswa')
        password = data.get('password')

        if not npm_mahasiswa or not password:
            return jsonify({"status": "error", "message": "npm_mahasiswa and password are required"}), 400

        # Cari mahasiswa di database
        query = "SELECT * FROM dataset_mahasiswa WHERE npm_mahasiswa = %s"
        cursor = db_connection.cursor(dictionary=True)
        cursor.execute(query, (npm_mahasiswa,))
        mahasiswa = cursor.fetchone()

        if not mahasiswa:
            return jsonify({"status": "error", "message": "Mahasiswa not found"}), 404

        # Validasi password (misalnya menggunakan bcrypt untuk perbandingan)
        if password != mahasiswa['npm_mahasiswa']:  # Periksa apakah password sesuai dengan npm_mahasiswa
            return jsonify({"status": "error", "message": "Invalid credentials"}), 401

        # Membuat JWT Token
        payload = {
            'npm_mahasiswa': mahasiswa['npm_mahasiswa'],
            'nama_mahasiswa': mahasiswa['nama_mahasiswa'],
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=1)  # Token akan kedaluwarsa dalam 1 jam
        }
        token = jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')

        # Simpan data pengguna di sesi (opsional, jika Anda juga ingin menggunakan session)
        session['npm_mahasiswa'] = mahasiswa['npm_mahasiswa']
        session['nama_mahasiswa'] = mahasiswa['nama_mahasiswa']

        # Kirim token ke client
        return jsonify({
            "status": "success",
            "message": "Login successful",
            "npm_mahasiswa": mahasiswa['npm_mahasiswa'],
            "nama_mahasiswa": mahasiswa['nama_mahasiswa'],
            "token": token  # Kirim token ke frontend
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# Logout endpoint
@app.route('/logout', methods=['POST'])
def logout():
        session.clear()
        return jsonify({"status": "success", "message": "Logout successful"})
    



@app.route('/rekomendasi', methods=['GET'])
def rekomendasi():
    try:
        # Mendapatkan token dari header Authorization
        token = request.headers.get('Authorization')

        if not token:
            return jsonify({"status": "error", "message": "Token is missing"}), 401

        # Memastikan format token adalah Bearer Token
        if token.startswith('Bearer '):
            token = token[7:]

        # Decode token JWT
        try:
            decoded_token = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            npm_mahasiswa = decoded_token.get('npm_mahasiswa')
            nama_mahasiswa = decoded_token.get('nama_mahasiswa')

            # Validasi jika informasi dari token tidak lengkap
            if not npm_mahasiswa or not nama_mahasiswa:
                return jsonify({"status": "error", "message": "Invalid token payload"}), 401

        except jwt.ExpiredSignatureError:
            return jsonify({"status": "error", "message": "Token has expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"status": "error", "message": "Invalid token"}), 401

        # Mengecek cache untuk cluster dan rata-rata
        if npm_mahasiswa in cluster_cache:
            cluster = cluster_cache[npm_mahasiswa]['cluster']
            rata_rata = cluster_cache[npm_mahasiswa]['rata_rata']
        else:
            # Query untuk mendapatkan data mahasiswa
            query = """
            SELECT 
                npm_mahasiswa,
                kategori_matakuliah,
                AVG(kode_nilai) AS rata_rata_nilai
            FROM dataset_krs
            GROUP BY npm_mahasiswa, kategori_matakuliah
            """
            try:
                df = pd.read_sql(query, db_connection)
            except Exception as db_error:
                return jsonify({"status": "error", "message": f"Database error: {str(db_error)}"}), 500

            df = df.drop_duplicates()

            pivot_df = df.pivot(
                index="npm_mahasiswa",
                columns="kategori_matakuliah",
                values="rata_rata_nilai"
            ).reset_index()

            # Menangani kolom duplikat dan missing values
            pivot_df.columns = pivot_df.columns.str.strip()
            pivot_df = pivot_df.loc[:, ~pivot_df.columns.duplicated()]

            if "Tugas Akhir" in pivot_df.columns:
                pivot_df.drop(columns=["Tugas Akhir"], inplace=True)

            pivot_df.fillna(0, inplace=True)

            # Normalisasi data
            scaler = MinMaxScaler()
            numeric_columns = pivot_df.columns[1:]
            normalized_data = pivot_df.copy()
            normalized_data[numeric_columns] = scaler.fit_transform(pivot_df[numeric_columns])

            # Prediksi cluster menggunakan model KMeans
            try:
                kmeans = load_model()  # Pastikan fungsi load_model() sudah benar
            except Exception as model_error:
                return jsonify({"status": "error", "message": f"Model loading error: {str(model_error)}"}), 500

            normalized_data['cluster'] = kmeans.predict(normalized_data[numeric_columns])
            pivot_df['cluster'] = normalized_data['cluster']

            # Menyimpan hasil ke cache
            for _, row in pivot_df.iterrows():
                rata_rata = {col: row[col] for col in numeric_columns}
                cluster_cache[row['npm_mahasiswa']] = {
                    "cluster": int(row['cluster']),
                    "rata_rata": rata_rata,
                }

            save_cache(cluster_cache)

            # Validasi jika mahasiswa tidak ditemukan
            if npm_mahasiswa not in cluster_cache:
                return jsonify({"status": "error", "message": "Student not found"}), 404

            cluster = cluster_cache[npm_mahasiswa]['cluster']
            rata_rata = cluster_cache[npm_mahasiswa]['rata_rata']

        # Mapping cluster ke kategori
        cluster_mapping = {
            0: "DKV",
            1: "PSI",
            2: "Umum"
        }
        category = cluster_mapping.get(cluster, "Unknown")

        # Query untuk mendapatkan kegiatan rekomendasi
        query_activities = """
        SELECT DISTINCT nama_kegiatan, kategori
        FROM dataset_kegiatanmahasiswa
        WHERE kategori = %s 
        AND nama_kegiatan NOT REGEXP '[0-9]{4}'
        AND nama_kegiatan NOT IN (
        SELECT nama_kegiatan
        FROM dataset_kegiatanmahasiswa
        WHERE npm_mahasiswa = %s
        )
        LIMIT 12

        """
        try:
            cursor = db_connection.cursor(dictionary=True)
            cursor.execute(query_activities, (category, npm_mahasiswa,))
            result = cursor.fetchall()
        except Exception as activity_error:
            return jsonify({"status": "error", "message": f"Activity query error: {str(activity_error)}"}), 500
        finally:
            cursor.close()

        # Konversi hasil ke DataFrame
        activities_df = pd.DataFrame(result)

        if activities_df.empty:
            return jsonify({
                "status": "error",
                "message": f"No activities found for category {category}"
            }), 404

        # Mengubah DataFrame ke list of dictionaries
        recommended_activities = activities_df.to_dict(orient="records")

        # Response berhasil
        return jsonify({
            "status": "success",
            "npm_mahasiswa": npm_mahasiswa,
            "nama_mahasiswa": nama_mahasiswa,
            "cluster": cluster,
            "category": category,
            "rata_rata": rata_rata,
            "recommended_activities": recommended_activities
        }), 200

    except Exception as e:
        # Menangani error global
        return jsonify({"status": "error", "message": f"Internal server error: {str(e)}"}), 500



@app.route('/studentdetail', methods=['GET'])
def studentDetail():
    try: 
        # Mendapatkan token dari header Authorization
        token = request.headers.get('Authorization')

        if not token:
            return jsonify({"success": False, "message": "Token is missing"}), 401
        
        if token.startswith('Bearer '):
            token = token[7:]  # Menghapus prefix 'Bearer '

        # Decode token JWT
        try:
            decoded_token = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            npm_mahasiswa = decoded_token.get('npm_mahasiswa')
            nama_mahasiswa = decoded_token.get('nama_mahasiswa')

            # Validasi jika informasi dari token tidak lengkap
            if not npm_mahasiswa or not nama_mahasiswa:
                return jsonify({"success": False, "message": "Invalid token payload"}), 401

        except jwt.ExpiredSignatureError:
            return jsonify({"status": "error", "message": "Token has expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"status": "error", "message": "Invalid token"}), 401
        
        # Koneksi ke database dan eksekusi query
        try:
            query = "SELECT * FROM dataset_mahasiswa WHERE npm_mahasiswa = %s"
            cursor = db_connection.cursor(dictionary=True)
            cursor.execute(query, (npm_mahasiswa,))
            student = cursor.fetchone()
        except Exception as db_error:
            return jsonify({"success": False, "message": f"Database error: {str(db_error)}"}), 500
        finally:
            cursor.close()  # Pastikan cursor selalu ditutup setelah digunakan
        
        # Jika data mahasiswa tidak ditemukan
        if not student:
            return jsonify({"success": False, "message": "Student not found"}), 404
        
        # Jika berhasil ditemukan
        return jsonify({
            "success": True,
            "message": "Student Detail data",
            "data": student
        }), 200

    except Exception as e:
        # Menangani error global
        return jsonify({"success": False, "message": f"Internal server error: {str(e)}"}), 500

        

@app.route('/kegiatanmahasiswa' )
def kegiatanMahasiswa():
    try:
        token = request.headers.get('Authorization')

        if not token:
            return jsonify({"success" : False , "message" : "Login first"})
        
        if token.startswith('Bearer '):
            token = token[7:]  # Remove the 'Bearer ' prefix
            # Decode the JWT token (assuming you have a secret key for JWT)
        try:
            decoded_token = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            npm_mahasiswa = decoded_token['npm_mahasiswa']
            nama_mahasiswa = decoded_token['nama_mahasiswa']
        except jwt.ExpiredSignatureError:
            return jsonify({"status": "error", "message": "Token has expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"status": "error", "message": "Invalid token"}), 401
        
        query = "SELECT * FROM dataset_kegiatanmahasiswa WHERE npm_mahasiswa = %s"
        cursor = db_connection.cursor(dictionary=True)
        cursor.execute(query, (npm_mahasiswa,))
        kegiatan = cursor.fetchall()

        if not kegiatan:
            return jsonify({"success" : False , "mesage" : "Kegiatan not found"}) , 404
        
        return jsonify({"success" : True  , "message" : "Kegiatan data by student" , "data" : kegiatan}),  200
    except Exception as e:
        return jsonify({"success" : False , "message" : str(e)}), 500
    finally:
        if db_connection is None:
            db_connection.close()








if __name__ == '__main__':
    app.run(debug=True)
