#!/usr/bin/env python3
"""
Script pour analyser chaque photo avec Claude Vision
et créer un dossier par image avec sa description.
"""

import os
import sys
import base64
import shutil
import subprocess
import time
import json
from pathlib import Path
import anthropic

SOURCE_DIR = Path("/home/user/traitement-de-photo/photos_extraites/MEDIA-main")
OUTPUT_DIR = Path("/home/user/traitement-de-photo/galerie_decrite")
PROGRESS_FILE = Path("/home/user/traitement-de-photo/progress.json")

SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".gif", ".webp", ".bmp"}
WDP_EXT = {".wdp"}

client = anthropic.Anthropic()


def convert_wdp_to_jpg(wdp_path: Path) -> Path | None:
    """Convertit un fichier WDP (JPEG XR) en JPEG via ImageMagick."""
    tmp = Path("/tmp") / (wdp_path.stem + "_converted.jpg")
    result = subprocess.run(
        ["convert", str(wdp_path), str(tmp)],
        capture_output=True, text=True
    )
    if result.returncode == 0 and tmp.exists():
        return tmp
    return None


def image_to_base64(img_path: Path) -> tuple[str, str]:
    """Retourne (base64_data, media_type)."""
    ext = img_path.suffix.lower()
    media_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif",
        ".webp": "image/webp", ".tiff": "image/tiff", ".tif": "image/tiff",
        ".bmp": "image/bmp",
    }
    media_type = media_map.get(ext, "image/jpeg")
    with open(img_path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    return data, media_type


def describe_image(img_path: Path) -> str:
    """Appelle Claude Vision pour obtenir une description de l'image."""
    b64, media_type = image_to_base64(img_path)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": b64,
                    },
                },
                {
                    "type": "text",
                    "text": (
                        "Décris cette image en français en 2-3 phrases courtes. "
                        "Sois précis sur le sujet principal, les couleurs dominantes "
                        "et l'ambiance générale."
                    ),
                },
            ],
        }],
    )
    return response.content[0].text.strip()


def load_progress() -> set:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return set(json.load(f))
    return set()


def save_progress(done: set):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(list(done), f)


def process_all():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    done = load_progress()

    all_files = sorted(SOURCE_DIR.iterdir())
    image_files = [
        f for f in all_files
        if f.suffix.lower() in SUPPORTED_EXT | WDP_EXT
    ]

    total = len(image_files)
    print(f"Total d'images à traiter : {total}")
    print(f"Déjà traités : {len(done)}\n")

    errors = []

    for idx, img_path in enumerate(image_files, 1):
        name = img_path.name
        if name in done:
            continue

        print(f"[{idx}/{total}] {name} ...", end=" ", flush=True)

        converted_tmp = None
        working_path = img_path

        # Convertir WDP si besoin
        if img_path.suffix.lower() in WDP_EXT:
            converted_tmp = convert_wdp_to_jpg(img_path)
            if converted_tmp is None:
                print("ERREUR conversion WDP")
                errors.append(name)
                continue
            working_path = converted_tmp

        # Convertir TIFF en JPEG si trop lourd pour l'API
        if img_path.suffix.lower() in {".tiff", ".tif"}:
            tmp_jpg = Path("/tmp") / (img_path.stem + "_tiff.jpg")
            r = subprocess.run(
                ["convert", str(working_path), str(tmp_jpg)],
                capture_output=True
            )
            if r.returncode == 0 and tmp_jpg.exists():
                converted_tmp = tmp_jpg
                working_path = tmp_jpg

        # Créer le dossier de sortie pour cette image
        stem = img_path.stem
        out_folder = OUTPUT_DIR / stem
        out_folder.mkdir(exist_ok=True)

        # Copier l'image originale dans le dossier
        dest_img = out_folder / name
        if not dest_img.exists():
            shutil.copy2(img_path, dest_img)

        # Obtenir la description
        try:
            desc = describe_image(working_path)
        except anthropic.BadRequestError:
            desc = "(Image non analysable : format ou contenu non supporté par l'API)"
            print("SKIP (format non supporté)", end=" ")
        except Exception as e:
            print(f"ERREUR API: {e}")
            errors.append(name)
            time.sleep(2)
            continue
        finally:
            # Nettoyer le fichier temporaire
            if converted_tmp and converted_tmp.exists():
                converted_tmp.unlink()

        # Écrire la description
        desc_file = out_folder / "description.txt"
        desc_file.write_text(f"Fichier : {name}\n\n{desc}\n", encoding="utf-8")

        print("OK")
        done.add(name)
        save_progress(done)

        # Petite pause pour respecter les limites de l'API
        time.sleep(0.3)

    print(f"\n✓ Terminé ! {len(done)} images traitées.")
    if errors:
        print(f"✗ Erreurs sur {len(errors)} fichiers : {errors}")


if __name__ == "__main__":
    process_all()
