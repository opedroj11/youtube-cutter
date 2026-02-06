# app.py
from flask import Flask, render_template, request, redirect, url_for, send_file
import os
import subprocess
import tempfile
from datetime import timedelta
import whisper
import shutil
import yt_dlp
import uuid

app = Flask(__name__)

# Diretório de saída
OUTPUT_DIR = "/content/videos_cortados"
os.makedirs(OUTPUT_DIR, exist_ok=True)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        video_url = request.form["video_url"].strip()
        keyword = request.form["keyword"].strip()
        with_subtitles = "subtitles" in request.form
        duration = int(request.form.get("duration", 90))

        if not video_url or not keyword:
            return render_template("index.html", error="Por favor, preencha todos os campos.")

        try:
            # Baixar vídeo
            ydl_opts = {
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'outtmpl': 'temp_video.mp4',
                'noplaylist': True,
                'quiet': False,
                'no_warnings': True,
                'ignoreerrors': True,
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
            }

            print("Baixando o vídeo...")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(video_url, download=True)
                video_file = "temp_video.mp4"
                title = info_dict['title']
                print(f"✅ Vídeo baixado: {title}")

            # Verificar se o arquivo existe
            if not os.path.exists("temp_video.mp4"):
                return render_template("index.html", error="Erro ao baixar o vídeo.")

            # Obter duração
            cmd_duration = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", "temp_video.mp4"]
            result = subprocess.run(cmd_duration, capture_output=True, text=True, check=True)
            video_duration = float(result.stdout.strip())

            # Extrair áudio
            audio_file = "temp_audio.wav"
            cmd_audio = ["ffmpeg", "-i", "temp_video.mp4", "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_file]
            subprocess.run(cmd_audio, check=True)

            # Carregar modelo Whisper
            model = whisper.load_model("base")
            result = model.transcribe(audio_file)

            # Gerar SRT (se desejar legenda)
            srt_file = "subtitles.srt"
            with open(srt_file, "w", encoding="utf-8") as f:
                for i, segment in enumerate(result["segments"]):
                    start_time = segment["start"]
                    end_time = segment["end"]
                    text = segment["text"].strip()

                    def format_time(seconds):
                        td = timedelta(seconds=seconds)
                        h, m, s = td.seconds // 3600, (td.seconds // 60) % 60, td.seconds % 60
                        return f"{h:02d}:{m:02d}:{s:02d},{int(td.microseconds / 1000):03d}"

                    start_str = format_time(start_time)
                    end_str = format_time(end_time)
                    f.write(f"{i+1}\n{start_str} --> {end_str}\n{text}\n\n")

            # Encontrar posições da palavra-chave
            keyword_positions = []
            for segment in result["segments"]:
                if keyword.lower() in segment["text"].lower():
                    start_time = segment["start"]
                    end_time = segment["end"]
                    keyword_positions.append((start_time, end_time))

            # Filtro: cada 90s (ou outro valor)
            filtered_positions = []
            last_end_time = -1

            for start_time, _ in keyword_positions:
                if start_time <= last_end_time:
                    continue
                filtered_positions.append(start_time)
                last_end_time = start_time + duration

            # Cortar vídeos
            output_dir = OUTPUT_DIR
            os.makedirs(output_dir, exist_ok=True)

            for i, start_time in enumerate(filtered_positions):
                output_name = os.path.join(output_dir, f"corte_{i+1}.mp4")
                end_time = start_time + duration

                if start_time < 0:
                    continue
                if end_time > video_duration:
                    end_time = video_duration

                # Comando FFmpeg
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-i", "temp_video.mp4",
                    "-ss", str(start_time),
                    "-to", str(end_time),
                ]

                # Se tiver legenda, aplicar
                if with_subtitles:
                    cmd += ["-vf", f"subtitles='{srt_file}'"]

                # Re-encode (não pode usar -c:v copy com -vf)
                cmd += ["-c:a", "aac", "-strict", "experimental", output_name]

                subprocess.run(cmd, check=True)

            # Limpar arquivos temporários
            os.remove("temp_audio.wav")
            os.remove("temp_video.mp4")
            os.remove(srt_file)

            # Redirecionar para download
            return redirect(url_for('download'))

        except Exception as e:
            return render_template("index.html", error=f"Erro: {e}")

    return render_template("index.html")

@app.route("/download")
def download():
    # Listar arquivos no diretório
    files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".mp4")]
    return render_template("download.html", files=files)

@app.route("/files/<filename>")
def serve_file(filename):
    return send_file(os.path.join(OUTPUT_DIR, filename), as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)
