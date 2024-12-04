import mysql.connector.cursor
import numpy as np 
from flask import Flask , request , jsonify
import joblib
import mysql.connector

app = Flask(__name__)

# config MySQL
db_config = {
    "host" : "localhost",
    "user" : "root",
    "password" : "" , 
    "database" : "sisrekomact"
}

def load_model():
    return joblib.load('kmeans_model.joblib')

# koneksi ke mysql 
def get_db_connection():
    conn = mysql.connector.connect(**db_config)
    return conn


@app.route('/')
def Home():
    return {"status" : "true" , "message" : "Berhasil menjalankan server"}

@app.route('/kegiatanmahasiswa' , methods=['POST'])
def get_kegiatan():
    try: 
        data = request.json 
        npm_mahasiswa = data.get('npm_mahasiswa')

        if not npm_mahasiswa:
            return jsonify({'error': 'npm_mahasiswa is required'}), 400
        
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # query for get data 
        query = 'SELECT * FROM dataset_kegiatanmahasiswa WHERE npm_mahasiswa = %s'
        cursor.execute(query , (npm_mahasiswa, ))
        result = cursor.fetchall()

          # Mengembalikan data dalam format JSON
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        connection.close()






@app.route('/recomend', methods=['POST'])
def recomend():
    try:
        data = request.json
        npm_mahasiswa = data.get('npm_mahasiswa')

        if not npm_mahasiswa:
            return jsonify({'error': "npm_mahasiswa is required"}), 400

        # Dapatkan koneksi ke database
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Ambil data mahasiswa untuk clustering dari database (termasuk nilai-nilai yang dibutuhkan)
        query_mahasiswa = '''
            SELECT 
                rata_rata_nilai_agama, rata_rata_nilai_animation, rata_rata_nilai_bahasa,
                rata_rata_nilai_basic_programming, rata_rata_nilai_basis_data, 
                rata_rata_nilai_computer_hardware, rata_rata_nilai_design, 
                rata_rata_nilai_ethics, rata_rata_nilai_game_making, 
                rata_rata_nilai_hardware, rata_rata_nilai_hukum, 
                rata_rata_nilai_jaringan, rata_rata_nilai_kewarganegaraan, 
                rata_rata_nilai_logical_thinking, rata_rata_nilai_logical_thingking, 
                rata_rata_nilai_machine_learning, rata_rata_nilai_manajemen, 
                rata_rata_nilai_marketing, rata_rata_nilai_mobile_development, 
                rata_rata_nilai_modelling, rata_rata_nilai_movie_making, 
                rata_rata_nilai_multimedia, rata_rata_nilai_pariwisata, 
                rata_rata_nilai_pemograman, rata_rata_nilai_startup, 
                rata_rata_nilai_tugas_akhir, rata_rata_nilai_website_making
            FROM dataset_mahasiswa WHERE npm_mahasiswa = %s
        '''
        cursor.execute(query_mahasiswa, (npm_mahasiswa,))
        mahasiswa = cursor.fetchone()

        if not mahasiswa:
            return jsonify({'error': 'Mahasiswa not found'}), 404

        # Siapkan data untuk clustering
        input_data = np.array([[mahasiswa[field] for field in mahasiswa.keys()]])

        # Muat model KMeans
        model = load_model()

        # Prediksi cluster berdasarkan data mahasiswa
        cluster = model.predict(input_data)

        # Update cluster mahasiswa di database
        cursor.execute(
            'UPDATE dataset_mahasiswa SET cluster = %s WHERE npm_mahasiswa = %s',
            (int(cluster[0]), npm_mahasiswa)
        )
        connection.commit()

        # Logika rekomendasi berdasarkan cluster
        if cluster == 0:
            query_kegiatan = "SELECT * FROM dataset_kegiatanmahasiswa WHERE kategori = 'DKV' LIMIT 10"
        elif cluster == 1:
            query_kegiatan = "SELECT * FROM dataset_kegiatanmahasiswa WHERE kategori = 'Umum' LIMIT 10"
        elif cluster == 2:
            query_kegiatan = "SELECT * FROM dataset_kegiatanmahasiswa WHERE kategori = 'PSI' LIMIT 10"
        else:
            return jsonify({'error': 'Cluster not recognized'}), 400

        # Eksekusi query untuk mendapatkan rekomendasi kegiatan
        cursor.execute(query_kegiatan)
        kegiatan = cursor.fetchall()

        # Jika tidak ada kegiatan yang sesuai
        if not kegiatan:
            return jsonify({'message': 'No recommended activities found'}), 200

        # Kembalikan hasil rekomendasi berdasarkan cluster yang baru
        return jsonify({'cluster': int(cluster[0]), 'rekomendasi_kegiatan': kegiatan}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

    finally:
        # Tutup sumber daya
        if 'cursor' in locals():
            cursor.close()
        if 'connection' in locals():
            connection.close()




@app.route('/predict', methods=['POST'])
def predict():
    try:
        data = request.get_json()
        print("Received data:", data)

        # Daftar field yang diperlukan
        required_fields = [
            "rata_rata_nilai_agama", "rata_rata_nilai_animation", "rata_rata_nilai_bahasa",
            "rata_rata_nilai_basic_programming", "rata_rata_nilai_basis_data", 
            "rata_rata_nilai_computer_hardware", "rata_rata_nilai_design", 
            "rata_rata_nilai_ethics", "rata_rata_nilai_game_making", 
            "rata_rata_nilai_hardware", "rata_rata_nilai_hukum", 
            "rata_rata_nilai_jaringan", "rata_rata_nilai_kewarganegaraan", 
            "rata_rata_nilai_logical_thinking", "rata_rata_nilai_logical_thingking", 
            "rata_rata_nilai_machine_learning", "rata_rata_nilai_manajemen", 
            "rata_rata_nilai_marketing", "rata_rata_nilai_mobile_development", 
            "rata_rata_nilai_modelling", "rata_rata_nilai_movie_making", 
            "rata_rata_nilai_multimedia", "rata_rata_nilai_pariwisata", 
            "rata_rata_nilai_pemograman", "rata_rata_nilai_startup", 
            "rata_rata_nilai_tugas_akhir", "rata_rata_nilai_website_making"
        ]

        # Validasi: cek field yang hilang atau None
        for field in required_fields:
            if field not in data or data[field] is None:
                return jsonify({"error": f"Missing value for {field}"}), 400

        # Format data untuk model
        input_data = np.array([[data[field] for field in required_fields]])

        # Muat model KMeans
        model = load_model()  # Pastikan load_model() mengembalikan model KMeans yang valid

        # Prediksi cluster
        cluster = model.predict(input_data)

        # Kembalikan hasil prediksi
        return jsonify({'cluster': int(cluster[0])}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)