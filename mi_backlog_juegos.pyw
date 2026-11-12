#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
My Game Backlog  (Mi Backlog de Juegos)
=======================================
Desktop app (Python + PyQt6) to keep track of the games you are playing or plan to play:

  * Cover art (found automatically, or pick one / paste it from the clipboard)
  * Title suggestions while you type (in case you mistype)
  * Platform (PC, PlayStation, Switch / Switch 2, Xbox...), platinum trophy and a Rerun tag
  * Metacritic score for the chosen platform and HowLongToBeat hours, filled in as you type the name
    (if Metacritic has no score for that platform, another one is used and you are warned)
  * Metacritic user score (0-10), also filled in automatically, and your own score
  * Index = Metacritic user score x 10 / sqrt(HowLongToBeat hours)  ->  higher score and fewer hours = better index
  * HowLongToBeat durations: story, story + extras and completionist (those that exist)
  * Colored statuses: Planned, Playing, Completed, Paused, Dropped
  * Filters and sorting by status, platform, platinum, reruns, scores, min/max hours and index
  * One list per year (2026 list, 2027 list...) and a tier list with covers for each list
  * Card view and list view, resizable sidebar, backup (export / import as .zip)
  * English / Spanish interface (English by default)

Run it:
    pip install -r requirements.txt
    python mi_backlog_juegos.pyw

Data is saved in  ~/.mi_backlog_juegos/
"""
import os
import sys
import json
import math
import time
import uuid
import queue
import difflib
import re
import shutil
import subprocess
import threading
import functools
import hashlib
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

from PyQt6.QtCore import Qt, QEvent, QMimeData, QRegularExpression, QSize, QRect, QRectF, QPoint, QObject, pyqtSignal, QTimer, QStringListModel, QUrl
from PyQt6.QtGui import (
    QPixmap, QPainter, QColor, QFont, QPen, QPainterPath, QGuiApplication, QFontMetrics,
    QShortcut, QKeySequence, QLinearGradient, QDesktopServices, QIcon, QPalette,
    QRegularExpressionValidator, QDrag,
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox, QDoubleSpinBox,
    QAbstractSpinBox, QCheckBox, QListWidget, QListWidgetItem, QListView,
    QAbstractItemView, QStyledItemDelegate, QStyle, QStackedWidget, QFileDialog,
    QMenu, QMessageBox, QFrame, QDialogButtonBox, QCompleter, QScrollArea, QInputDialog, QSplitter, QSizePolicy, QColorDialog, QLayout,
)

# --------------------------------------------------------------------------
# Data and settings
# --------------------------------------------------------------------------
DATA_DIR = Path.home() / ".mi_backlog_juegos"
COVERS_DIR = DATA_DIR / "covers"
GAMES_FILE = DATA_DIR / "games.json"
CONFIG_FILE = DATA_DIR / "config.json"

STATUS_COLORS = {
    "Planeado": "#8b93ad",
    "Jugando": "#4c9be8",
    "Completado": "#3ecf6e",   # green
    "Pausado": "#f2c94c",      # yellow
    "Dropeado": "#ef5b5b",     # red
}
STATUSES = list(STATUS_COLORS)

PLATFORMS = [
    "PC", "PlayStation 5", "PlayStation 4", "PlayStation 3",
    "Nintendo Switch 2", "Nintendo Switch", "Nintendo 3DS", "Nintendo DS",
    "Xbox Series X|S", "Xbox One", "Xbox 360", "Emulador", "Otra",
]
PLATFORM_SHORT = {
    "PC": "PC", "PlayStation 5": "PS5", "PlayStation 4": "PS4", "PlayStation 3": "PS3",
    "Nintendo Switch 2": "SWITCH 2", "Nintendo Switch": "SWITCH", "Nintendo 3DS": "3DS", "Nintendo DS": "DS",
    "Xbox Series X|S": "XBOX S/X", "Xbox One": "XBOX ONE", "Xbox 360": "X360", "Emulador": "EMU", "Otra": "OTRA",
}
# Names the web sources (Metacritic / HowLongToBeat) use for each platform (normalized: lowercase, no symbols)
PLATFORM_ALIASES = {
    "PC": {"pc", "windows", "pcmicrosoftwindows"},
    "PlayStation 5": {"playstation5", "ps5"},
    "PlayStation 4": {"playstation4", "ps4"},
    "PlayStation 3": {"playstation3", "ps3"},
    "Nintendo Switch 2": {"nintendoswitch2", "switch2"},
    "Nintendo Switch": {"nintendoswitch", "switch"},
    "Nintendo 3DS": {"nintendo3ds", "3ds", "new3ds", "newnintendo3ds", "nintendo2ds", "2ds"},
    "Nintendo DS": {"nintendods", "ds", "nintendodsi", "dsi"},
    "Xbox Series X|S": {"xboxseriessx", "xboxseriesxs", "xboxseriesx", "xboxseriess", "xboxseries"},
    "Xbox One": {"xboxone"},
    "Xbox 360": {"xbox360"},
    "Emulador": set(),   # how you play, not a system: the websites never list it
    "Otra": set(),
}

ROLE_ID = Qt.ItemDataRole.UserRole.value

# --------------------------------------------------------------------------
# Languages: English by default, Spanish optional.
# Strings in the code are written in English; ES maps each one to its Spanish
# translation. The values stored in games.json (statuses, the platforms "Otra" and "Emulador")
# stay in Spanish so lists made with older versions keep working: they are only
# translated when they are shown on screen.
# --------------------------------------------------------------------------
LANG = "en"
LANGUAGES = [("en", "English"), ("es", "Español")]

STATUS_LABELS_EN = {"Planeado": "Planned", "Jugando": "Playing", "Completado": "Completed",
                    "Pausado": "Paused", "Dropeado": "Dropped"}
SORT_LABELS_EN = {"Índice": "Index", "Mi nota": "My score", "Nota Metacritic": "Metacritic score",
                  "Nota usuarios Metacritic": "Metacritic user score", "Horas": "Hours", "Nombre": "Name", "Fecha añadido": "Date added"}

ES = {
    # --- messages from the web lookups ---
    "HowLongToBeat: no hours found": "HowLongToBeat: sin horas",
    "Missing 'howlongtobeatpy' (pip install howlongtobeatpy): no hours or platforms":
        "Falta 'howlongtobeatpy' (pip install howlongtobeatpy): sin horas ni plataformas",
    "HowLongToBeat did not respond ({err})": "HowLongToBeat no respondió ({err})",
    "HowLongToBeat: game not found": "HowLongToBeat: no encontré ese juego",
    "Steam did not respond ({err})": "Steam no respondió ({err})",
    "No cover found automatically (choose or paste one yourself)":
        "Sin carátula automática (elige una imagen o pégala tú)",
    "Metacritic: could not read the page (use “Open Metacritic” and enter the score by hand)":
        "Metacritic: no pude leer la ficha (usa «Abrir Metacritic» y apunta la nota a mano)",
    "Metacritic: title page not found": "Metacritic: no encontré la ficha de ese título",
    "Metacritic responded with error {code}": "Metacritic respondió con error {code}",
    "Metacritic did not respond ({err})": "Metacritic no respondió ({err})",
    "Metacritic has no score for {platform}": "Metacritic no tiene nota para {platform}",
    " (it does for: {names})": " (sí para: {names})",
    "Metacritic: no score": "Metacritic: sin nota",

    # --- add / edit game dialog ---
    "Edit game": "Editar juego",
    "Add game": "Añadir juego",
    "Choose image…": "Elegir imagen…",
    "Paste from clipboard": "Pegar del portapapeles",
    "Type the name: I'll suggest titles in case you mistype…":
        "Escribe el nombre: te sugiero títulos por si te equivocas…",
    "Game": "Juego",
    "You can pick any platform, even one the game is not detected on. The Metacritic score is looked up for "
    "the chosen one; if Metacritic does not have it you get a warning and the score of another platform":
        "Puedes elegir cualquier plataforma, aunque no se detecte en el juego. Con la elegida se busca la nota "
        "de Metacritic; si Metacritic no la tiene, se avisa y se usa la de otra plataforma",
    " (you can still pick any other platform)": " (puedes elegir cualquier otra igualmente)",
    "⚠ Metacritic has no score for {platform}: using the one from {used} ({score}). "
    "Check it, or choose the right platform or type the score by hand.":
        "⚠ Metacritic no tiene nota para {platform}: se ha puesto la de {used} ({score}). "
        "Compruébala, o elige la plataforma correcta o escribe la nota a mano.",
    "⚠ Metacritic does not list scores by platform for this game: using its general "
    "score ({score}). Check it.":
        "⚠ Metacritic no desglosa la nota por plataformas en este juego: se ha puesto su nota general "
        "({score}). Compruébala.",
    "— Not specified —": "— Sin especificar —",
    "Platform": "Plataforma",
    "Status": "Estado",
    "🏆  Platinum earned": "🏆  Platino conseguido",
    "🔁  Rerun (replaying)": "🔁  Rerun (rejugado)",
    "Tick this if you are replaying this game: a RERUN tag will show on its card":
        "Márcalo si estás rejugando este juego: se verá una etiqueta RERUN en su tarjeta",
    "No score": "Sin nota",
    "My score (0–10)": "Mi nota (0–10)",
    "Metacritic score": "Nota Metacritic",
    "Index hours (HLTB)": "Horas del índice (HLTB)",
    "Story (h)": "Historia (h)",
    "Story + extras (h)": "Historia + extras (h)",
    "Completionist (h)": "Completista (h)",
    "Comments…": "Comentarios…",
    "Notes": "Notas",
    "Index: — (needs the Metacritic user score and hours)": "Índice: — (necesita la nota de usuarios de Metacritic y las horas)",
    "Index: {v}": "Índice: {v}",
    "✨  Autofill": "✨  Autocompletar",
    "Looks up cover art, Metacritic score (for the chosen platform) and HowLongToBeat hours (overwrites what is there)":
        "Busca carátula, nota de Metacritic (de la plataforma elegida) y horas "
        "de HowLongToBeat (sobrescribe lo que haya)",
    "Open Metacritic": "Abrir Metacritic",
    "Opens the Metacritic search so you can check the score or enter it by hand":
        "Abre la búsqueda en Metacritic por si quieres comprobar o apuntar la nota a mano",
    "Open HowLongToBeat": "Abrir HowLongToBeat",
    "Opens the game page on HowLongToBeat so you can check the hours or enter them by hand":
        "Abre la página del juego en HowLongToBeat para comprobar o apuntar las horas a mano",
    "Save": "Guardar",
    "Cancel": "Cancelar",
    "No cover": "Sin carátula",
    "Choose cover": "Elegir carátula",
    "Images (*.png *.jpg *.jpeg *.webp *.bmp)": "Imágenes (*.png *.jpg *.jpeg *.webp *.bmp)",
    "There is no image on the clipboard.": "No hay ninguna imagen en el portapapeles.",
    "Available on: ": "Disponible en: ",
    "Press ✨ Autofill to look up the score for this platform.":
        "Pulsa ✨ Autocompletar para buscar la nota de esta plataforma.",
    "🔎 Searching…": "🔎 Buscando…",
    "name corrected to “{name}”": "nombre corregido a «{name}»",
    "cover": "carátula",
    "platform ({p})": "plataforma ({p})",
    "hours": "horas",
    "Nothing found, fill it in by hand.": "Nada encontrado, rellénalo a mano.",
    "Give the game a name.": "Pon un nombre al juego.",
    "List": "Lista",
    "You can also drop an image here (a file or one dragged from the browser)":
        "También puedes soltar aquí una imagen (un archivo o una arrastrada desde el navegador)",
    "Downloading the image…": "Descargando la imagen…",
    "That link is not an image I can use: save it and choose it with “Choose image…”.":
        "Ese enlace no es una imagen que pueda usar: guárdala y elígela con «Elegir imagen…».",
    "⚠ This Metacritic score is from {used}, not from {platform}: Metacritic has none for it.":
        "⚠ Esta nota de Metacritic es de {used}, no de {platform}: Metacritic no tiene nota para esa.",
    "⚠ This is the general Metacritic score: Metacritic does not list it by platform for this game.":
        "⚠ Es la nota general de Metacritic: en este juego no la desglosa por plataformas.",
    "🔎 Searching… the game will be saved as soon as the search finishes.":
        "🔎 Buscando… el juego se guardará en cuanto termine la búsqueda.",
    "Game already in the list": "Juego repetido",
    "“{name}” is already in the {year} list. Save it anyway?":
        "«{name}» ya está en la lista {year}. ¿Guardarlo igualmente?",
    "Save anyway": "Guardar igualmente",

    # --- game cards / list rows ---
    "Story": "Historia",
    "Complete": "Completista",
    "You": "Tú",
    "Hours": "Horas",
    "Index": "Índice",

    # --- tier list ---
    "Tier list · {year} list": "Tier list · Lista {year}",
    "Tier list {year}": "Tier list {year}",
    "Drag the covers to their row. Use ▲ ▼ to move a row and ⚙ for its options (color, "
    "rename, add, clear, delete); double-click a row name to rename it. Deleting a row "
    "never deletes games: they go back to “Unranked”. Zoom: − / + buttons or Ctrl + mouse wheel.":
        "Arrastra las portadas a su fila. Usa ▲ ▼ para mover un puesto y ⚙ para sus opciones (color, "
        "renombrar, añadir, vaciar, eliminar); doble clic en el nombre para renombrarlo. Eliminar un puesto "
        "nunca borra juegos: vuelven a «Sin clasificar». Zoom: botones − / + o Ctrl + rueda.",
    "🔁  Hide reruns": "🔁  Ocultar reruns",
    "🏷  Mark reruns": "🏷  Marcar reruns",
    "Hide the games marked as Rerun (they keep their place in the tier list)":
        "Oculta los juegos marcados como Rerun (conservan su puesto en el tier list)",
    "Show a RERUN tag at the bottom of the covers of games marked as Rerun":
        "Muestra una etiqueta RERUN abajo en la portada de los juegos marcados como Rerun",
    "No game in this list is marked as Rerun": "Ningún juego de esta lista está marcado como Rerun",
    "🚫  Hide dropped": "🚫  Ocultar dropeados",
    "🏷  Mark dropped": "🏷  Marcar dropeados",
    "Hide the games with Dropped status (they keep their place in the tier list)":
        "Oculta los juegos en estado Dropeado (conservan su puesto en el tier list)",
    "Show a DROPPED tag at the top left of the covers of the dropped games":
        "Muestra una etiqueta DROPEADO arriba a la izquierda en la portada de los juegos dropeados",
    "No game in this list is Dropped": "Ningún juego de esta lista está Dropeado",
    "DROPPED": "DROPEADO",
    "🏆  Mark platinums": "🏆  Marcar platinos",
    "Show a platinum trophy on the covers of the games with the platinum earned":
        "Muestra un trofeo de platino en la portada de los juegos con el platino conseguido",
    "No game in this list has the platinum earned": "Ningún juego de esta lista tiene el platino conseguido",
    "Move row up": "Subir puesto",
    "Move row down": "Bajar puesto",
    "Row options: color, rename, move, add, clear, delete": "Opciones del puesto: color, renombrar, mover, añadir, vaciar, eliminar",
    "Custom color…": "Color personalizado…",
    "Row color": "Color del puesto",
    "Add row above": "Añadir puesto arriba",
    "Add row below": "Añadir puesto abajo",
    "Clear row (covers go back to “Unranked”)": "Vaciar puesto (las portadas vuelven a «Sin clasificar»)",
    "Delete row (its covers go back to “Unranked”)": "Eliminar puesto (sus portadas vuelven a «Sin clasificar»)",
    "Zoom out (Ctrl + wheel down)": "Alejar (Ctrl + rueda hacia abajo)",
    "Zoom in (Ctrl + wheel up)": "Acercar (Ctrl + rueda hacia arriba)",
    "+ Row": "+ Fila",
    "Reset": "Reiniciar",
    "Save photo to {year}": "Guardar foto en {year}",
    "Saves the tier list photo into the {year} list (it is also saved automatically on close)":
        "Guarda la foto del tier list en la lista {year} (también se guarda sola al cerrar)",
    "Open photo": "Abrir foto",
    "Opens this year's saved photo": "Abre la foto guardada de este año",
    "Export…": "Exportar…",
    "Save the photo to another folder": "Guardar la foto en otra carpeta",
    "Close": "Cerrar",
    "Unranked": "Sin clasificar",
    "Rename row": "Renombrar fila",
    "Row name:": "Nombre de la fila:",
    "Rename": "Renombrar",
    "Delete row": "Eliminar fila",
    "New": "Nueva",
    "Reset tier list": "Reiniciar tier list",
    "Move all covers back to “Unranked”?": "¿Devolver todas las portadas a «Sin clasificar»?",
    "Place a cover in a row before saving the photo.":
        "Coloca alguna portada en una fila antes de guardar la foto.",
    "Photo saved in the {year} list: {path}": "Foto guardada en la lista {year}: {path}",
    "Could not save the photo.": "No se pudo guardar la foto.",
    "There is no saved photo for this year yet: press “Save photo”.":
        "Aún no hay foto guardada para este año: pulsa «Guardar foto».",
    "Export tier list": "Exportar tier list",
    "PNG image (*.png)": "Imagen PNG (*.png)",
    "Image saved to {path}": "Imagen guardada en {path}",
    "Could not save the image.": "No se pudo guardar la imagen.",
    "Double-click: rename · Right-click: row options":
        "Doble clic: renombrar · Clic derecho: opciones del puesto",
    "Red": "Rojo", "Orange": "Naranja", "Yellow": "Amarillo", "Green": "Verde", "Teal": "Turquesa",
    "Blue": "Azul", "Violet": "Violeta", "Pink": "Rosa", "Gray": "Gris",

    # --- backups ---
    "That file is not a My Game Backlog backup.": "Ese archivo no es una copia de Mi Backlog de Juegos.",
    "The backup is too large.": "La copia es demasiado grande.",
    "The backup does not contain the game list.": "La copia no contiene la lista de juegos.",
    "The backup's game list is not valid.": "La lista de juegos de la copia no es válida.",

    # --- main window ---
    "My Game Backlog": "Mi Backlog de Juegos",
    "🎮  My Backlog": "🎮  Mi Backlog",
    "Higher score and fewer hours = better index": "Más nota y menos horas = mejor índice",
    "Sort by": "Ordenar por",
    "Hours to finish": "Horas para pasárselo",
    "Backup": "Copia de seguridad",
    "Language": "Idioma",
    "⚙  Settings": "⚙  Ajustes",
    "Language, theme, backups and updates": "Idioma, tema, copias de seguridad y actualizaciones",
    "Update the HowLongToBeat connection": "Actualizar la conexión con HowLongToBeat",
    "It could not be updated:\n\n{err}": "No se pudo actualizar:\n\n{err}",
    "The HowLongToBeat connection is already up to date (version {v}).":
        "La conexión con HowLongToBeat ya está al día (versión {v}).",
    "The HowLongToBeat connection was updated from version {old} to {new}.\n\n"
    "Close the app and open it again to use it.":
        "La conexión con HowLongToBeat se ha actualizado de la versión {old} a la {new}.\n\n"
        "Cierra la app y vuelve a abrirla para usarla.",
    "In the .exe version the connection is built into the program, so it cannot be "
    "updated from here: download the newest .exe. (With the Python version, "
    "mi_backlog_juegos.pyw, this option updates it by itself.)":
        "En la versión .exe la conexión va dentro del programa y no se puede actualizar desde aquí: "
        "descarga el .exe más nuevo. (Con la versión de Python, mi_backlog_juegos.pyw, esta opción la "
        "actualiza sola.)",
    "Check for updates (version {v})…": "Buscar actualizaciones (versión {v})…",
    "Check for updates": "Buscar actualizaciones",
    "Looking for a new version of the app…": "Buscando una versión nueva de la app…",
    "Could not check for updates ({err}). Check your internet connection.":
        "No se pudo buscar actualizaciones ({err}). Comprueba tu conexión a internet.",
    "No version of the app has been published yet.": "Todavía no se ha publicado ninguna versión de la app.",
    "You have the latest version ({v}).": "Tienes la última versión ({v}).",
    "Version {v} is published, but without the .exe yet. Try again later.":
        "La versión {v} está publicada, pero todavía sin el .exe. Vuelve a probar más tarde.",
    "There is a new version: {new} (you have {old}).": "Hay una versión nueva: {new} (tienes la {old}).",
    "What is new:": "Novedades:",
    "It will be downloaded, the app will close and the new version will open. Your games are not touched.":
        "Se descargará, la app se cerrará y se abrirá la versión nueva. Tus juegos no se tocan.",
    "Update now": "Actualizar ahora",
    "Not now": "Ahora no",
    "Downloading version {v}…": "Descargando la versión {v}…",
    "Version {v} is ready. The app will now close and open again.":
        "La versión {v} está lista. La app se cerrará y se volverá a abrir.",
    "This copy of the app is a folder, not a single .exe, so it cannot update itself: "
    "download the new version from GitHub.":
        "Esta copia de la app es una carpeta, no un único .exe, así que no puede actualizarse sola: "
        "descarga la versión nueva desde GitHub.",
    "The new version has no .exe attached.": "La versión nueva no tiene el .exe adjunto.",
    "The app cannot write in its own folder. Move it to a folder of yours (for example "
    "Documents or the Desktop) and try again.":
        "La app no puede escribir en su propia carpeta. Muévela a una carpeta tuya (por ejemplo "
        "Documentos o el Escritorio) y vuelve a probar.",
    "The download arrived incomplete or damaged, so nothing was changed. Try again.":
        "La descarga llegó incompleta o dañada, así que no se ha cambiado nada. Vuelve a probar.",
    "The update could not be downloaded ({err}). Check your internet connection.":
        "No se pudo descargar la actualización ({err}). Comprueba tu conexión a internet.",
    "Looking for a new version of the HowLongToBeat connection…":
        "Buscando una versión nueva de la conexión con HowLongToBeat…",
    "Theme": "Tema",
    "Dark": "Oscuro",
    "Black": "Negro",
    "Light": "Claro",
    "Could not add the game": "No se pudo añadir el juego",
    "Something went wrong while adding “{name}”: {err}\n\nThe details are in error.log, inside the folder {folder}":
        "Algo falló al añadir «{name}»: {err}\n\nLos detalles están en error.log, dentro de la carpeta {folder}",
    "Change the language or export / import a backup": "Cambiar el idioma o exportar / importar una copia de seguridad",
    "All": "Todas",
    "🏆  Platinum only": "🏆  Solo platinados",
    "🔁  Reruns only": "🔁  Solo reruns",
    "↓  Highest first": "↓  Mayor primero",
    "↑  Lowest first": "↑  Menor primero",
    "Min h": "Mín h",
    "Max h": "Máx h",
    "Reset filters": "Restablecer filtros",
    "Export backup…": "Exportar copia…",
    "Saves your games, covers, tier lists and settings into a .zip":
        "Guarda tus juegos, carátulas, tier lists y ajustes en un .zip",
    "Import backup…": "Importar copia…",
    "Restores a .zip backup (yours or a friend's)": "Recupera una copia .zip (la tuya o la de un amigo)",
    "Show or hide the sidebar (Ctrl+B)": "Mostrar u ocultar la barra lateral (Ctrl+B)",
    "Card view": "Vista de tarjetas",
    "List view with thumbnails and details": "Vista de lista con miniaturas y detalles",
    "Search game…   (Ctrl+F)": "Buscar juego…   (Ctrl+F)",
    "List options: new list for another year, delete this list":
        "Opciones de la lista: lista nueva para otro año, borrar esta lista",
    "+ New list for another year…": "+ Lista nueva para otro año…",
    "Delete the {year} list…": "Borrar la lista {year}…",
    "Open the tier list of this list": "Abrir el tier list de esta lista",
    "+  Add game": "+  Añadir juego",
    "List {year}": "Lista {year}",
    "This list has no games yet.\nPress  + Add game  and type the name:\ncover, score and hours fill in on their own.":
        "Esta lista aún no tiene juegos.\nPulsa  + Añadir juego  y escribe el nombre:\n"
        "la carátula, la nota y las horas se rellenan solas.",
    "No game matches the current filters.": "Ningún juego cumple los filtros actuales.",
    "List {year}  ·  {shown} of {total} games  ·  {done} completed  ·  🏆 {plats} platinums  ·  "
    "{hours} h of pending backlog (planned, playing and paused)":
        "Lista {year}  ·  {shown} de {total} juegos  ·  {done} completados  ·  🏆 {plats} platinos  ·  "
        "{hours} h de backlog pendiente (planeados, jugando y pausados)",
    "  ·  🏆 Platinum": "  ·  🏆 Platino",
    "There is no saved tier list for {year} yet.\nClick to open it: it is saved when you close it.":
        "Aún no hay un tier list guardado para {year}.\nHaz clic para abrirlo: se guarda al cerrarlo.",
    "Click to open the tier list": "Clic para abrir el tier list",
    "Click to open the photo at full size": "Clic para abrir la foto a tamaño completo",
    "Export backup": "Exportar copia de seguridad",
    "Backup (*.zip)": "Copia de seguridad (*.zip)",
    "Could not export": "No se pudo exportar",
    "Backup created": "Copia creada",
    "Backup saved to:\n{path}\n\n{n} games with their covers and tier lists.":
        "Copia guardada en:\n{path}\n\n{n} juegos con sus carátulas y tier lists.",
    "Import backup": "Importar copia de seguridad",
    "Import a backup": "Importar copia",
    "The backup has {n} games, {new} of them that you don't have now.\n\n"
    "Replace: your list becomes the backup's (a backup of yours is saved first).\n"
    "Add: only the games you are missing are added and nothing of yours is touched.":
        "La copia tiene {n} juegos, {new} de ellos que no tienes ahora.\n\n"
        "Reemplazar: tu lista pasa a ser la de la copia (antes se guarda una copia de la tuya).\n"
        "Añadir: se suman solo los juegos que te faltan y no se toca nada de lo tuyo.",
    "Replace my data": "Reemplazar mis datos",
    "Add what is missing": "Añadir lo que falte",
    "Could not import": "No se pudo importar",
    "Backup imported": "Copia importada",
    "Your list now has {n} games.\n\nBefore replacing, a copy of the previous data was saved to:\n{path}":
        "Tu lista ahora tiene {n} juegos.\n\nAntes de reemplazar se guardó una copia de lo anterior en:\n{path}",
    "{n} new games were added.": "Se añadieron {n} juegos nuevos.",
    "No game was missing: everything was already in your list.":
        "No faltaba ningún juego: todo estaba ya en tu lista.",
    "New list": "Nueva lista",
    "List year (for example 2027):": "Año de la lista (por ejemplo 2027):",
    "Invalid year": "Año no válido",
    "Enter a year between 1980 and 2100.": "Escribe un año entre 1980 y 2100.",
    "Delete the {year} list?": "¿Borrar la lista {year}?",
    "\nIts {n} games, covers and tier list will be deleted. This cannot be undone.":
        "\nSe eliminarán sus {n} juegos, sus carátulas y su tier list. No se puede deshacer.",
    "Delete list": "Borrar lista",
    "Yes, delete": "Borrar",
    "The {year} list has no games yet.": "La lista {year} aún no tiene juegos.",
    "The {year} list has no games to rank yet (Planned games are not included in the tier list).":
        "La lista {year} aún no tiene juegos que clasificar (los Planeados no entran en el tier list).",
    "Delete": "Eliminar",
    "Del": "Supr",
    "“{name}” deleted.": "«{name}» eliminado.",
    "Undo": "Deshacer",
    "“{name}” moved to the {year} list.": "«{name}» movido a la lista {year}.",
    "Move to list": "Mover a la lista",
    "Move or copy games to another list…": "Mover o copiar juegos a otra lista…",
    "Move or copy games": "Mover o copiar juegos",
    "Pass games from the {year} list to another one": "Pasar juegos de la lista {year} a otra",
    "Useful at the end of the year: what you did not get to play goes on to the next "
    "list, and the completed ones stay in this one.":
        "Útil al acabar el año: lo que no llegaste a jugar pasa a la lista siguiente y los "
        "completados se quedan en esta.",
    "Which games": "Qué juegos",
    "To the list": "A la lista",
    "  (new)": "  (nueva)",
    "How": "Cómo",
    "Move (they leave the {year} list)": "Mover (salen de la lista {year})",
    "Copy (they also stay in the {year} list)": "Copiar (se quedan también en la lista {year})",
    "Games that will be moved to the {year} list: {n}": "Juegos que se moverán a la lista {year}: {n}",
    "Games that will be copied to the {year} list: {n}": "Juegos que se copiarán a la lista {year}: {n}",
    "Already in that list (left as they are): {n}":
        "Ya están en esa lista (se dejan como están): {n}",
    "Games moved to the {year} list: {n}": "Juegos movidos a la lista {year}: {n}",
    "Games copied to the {year} list: {n}": "Juegos copiados a la lista {year}: {n}",
    "  ·  already there, left as they were: {n}": "  ·  ya estaban y se han dejado igual: {n}",
    "Move": "Mover",
    "{n} selected (right-click to act on all of them, Esc to unselect)":
        "{n} seleccionados (clic derecho para actuar sobre todos, Esc para quitar la selección)",
    "{n} games selected": "{n} juegos seleccionados",
    "Move or copy to another list…": "Mover o copiar a otra lista…",
    "Delete {n} games": "Eliminar {n} juegos",
    "Games deleted: {n}": "Juegos eliminados: {n}",
    "Pass the {n} selected games to another list": "Pasar los {n} juegos seleccionados a otra lista",
    "Copy": "Copiar",
    "Problem reading your list": "Problema al leer tu lista",
    "Your game list (games.json) could not be read, so the automatic copy from {date} was "
    "loaded ({n} games).\n\nThe damaged file was kept here, in case you need it:\n{path}":
        "No se pudo leer tu lista de juegos (games.json), así que se ha cargado la copia automática del "
        "{date} ({n} juegos).\n\nEl archivo dañado se ha guardado aquí, por si lo necesitas:\n{path}",
    "Your game list (games.json) could not be read and there is no automatic copy to "
    "recover it from. You can import a backup from ⚙.\n\nThe damaged file was kept here:\n{path}":
        "No se pudo leer tu lista de juegos (games.json) y no hay ninguna copia automática para "
        "recuperarla. Puedes importar una copia de seguridad desde ⚙.\n\nEl archivo dañado se ha guardado aquí:\n{path}",
    "Unnamed": "Sin nombre",
    "Metacritic user score (0–10)": "Nota usuarios Metacritic (0–10)",
    "user score": "nota de usuarios",
    "Meta Users": "Meta Usuarios",
    "Delete photo": "Borrar foto",
    "Removes this saved photo from the sidebar. Open the tier list to save a new one.":
        "Quita esta foto guardada de la barra lateral. Abre el tier list para guardar una nueva.",
    "Delete the saved photo of the {year} tier list?\nThe tier list itself is kept: open it to save a new photo.":
        "¿Borrar la foto guardada del tier list {year}?\nEl tier list se conserva: ábrelo para guardar una foto nueva.",
    "  ·  Users {v}": "  ·  Usuarios {v}",
    "Edit": "Editar",
    "Change status": "Cambiar estado",
}


def set_language(code):
    global LANG
    LANG = code if code in dict(LANGUAGES) else "en"


def tr(text, **kw):
    """Translate an English UI string (Spanish if selected). **kw fills the {placeholders}."""
    out = ES.get(text, text) if LANG == "es" else text
    return out.format(**kw) if kw else out


def status_label(s):
    return STATUS_LABELS_EN.get(s, s) if LANG == "en" else s


def sort_label(n):
    return SORT_LABELS_EN.get(n, n) if LANG == "en" else n


PLATFORM_LABEL_EN = {"Otra": "Other", "Emulador": "Emulator"}


def plat_label(p):
    return PLATFORM_LABEL_EN.get(p, p) if LANG == "en" else p


def plat_short(p):
    if p == "Otra":
        return "OTHER" if LANG == "en" else "OTRA"
    return PLATFORM_SHORT.get(p, p.upper())


_WINDOWS = []   # keeps the main windows alive (the language switch opens a new one)



def ensure_dirs():
    COVERS_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, data):
    ensure_dirs()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


AUTO_DIR = DATA_DIR / "backups" / "auto"   # one automatic copy of games.json per day
AUTO_KEEP = 10                             # how many daily copies are kept


def _read_game_list(path):
    """The list of games in a JSON file, or None if the file cannot be read or is not a list."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return [g for g in data if isinstance(g, dict)] if isinstance(data, list) else None


def snapshot_games():
    """Keep a copy of games.json (only called when it was read correctly): one per day, the last AUTO_KEEP."""
    try:
        AUTO_DIR.mkdir(parents=True, exist_ok=True)
        today = AUTO_DIR / f"games_{time.strftime('%Y-%m-%d')}.json"
        if not today.exists():
            shutil.copy2(GAMES_FILE, today)
        for old in sorted(AUTO_DIR.glob("games_*.json"))[:-AUTO_KEEP]:
            old.unlink()
    except OSError:
        pass


def load_games():
    """
    (games, problem). If games.json exists but cannot be read, it is never overwritten blindly (that would
    lose the whole list): a copy is kept as games.corrupt-<date>.json and the newest automatic daily copy
    that can be read is loaded instead. 'problem' is None, or (corrupt copy, daily copy used or None).
    """
    if not GAMES_FILE.exists():
        return [], None
    games = _read_game_list(GAMES_FILE)
    if games is not None:
        snapshot_games()
        return games, None
    bad = GAMES_FILE.with_name(f"games.corrupt-{time.strftime('%Y%m%d_%H%M%S')}.json")
    try:
        shutil.copy2(GAMES_FILE, bad)
    except OSError:
        bad = GAMES_FILE
    for snap in sorted(AUTO_DIR.glob("games_*.json"), reverse=True):
        games = _read_game_list(snap)
        if games is not None:
            save_json(GAMES_FILE, games)
            return games, (bad, snap)
    return [], (bad, None)


def new_game():
    return {
        "id": uuid.uuid4().hex,
        "name": "",
        "cover": "",
        "my_score": None,     # 0-10
        "meta_score": None,   # 0-100
        "user_score": None,   # Metacritic user score (0-10)
        "hours": None,        # default HowLongToBeat hours (the ones used for the index)
        "hours_main": None,   # main story
        "hours_extra": None,  # story + extras
        "hours_100": None,    # completionist
        "year": None,         # list (year) the game belongs to
        "status": "Planeado",
        "platform": "",       # one of PLATFORMS, or empty
        "hltb_id": None,      # HowLongToBeat game id (if it was picked from the suggestions)
        "platinum": False,    # platinum trophy earned
        "rerun": False,       # being replayed (the game stays in the list of its year)
        "meta_platform": None,  # platform the Metacritic score belongs to (when it was filled in automatically)
        "meta_other": False,    # True if that score is NOT from the chosen platform (Metacritic had none for it)
        "notes": "",
        "added": time.time(),
    }


# --------------------------------------------------------------------------
# Index: score / time
# --------------------------------------------------------------------------
def base_score(g):
    """Score 0-100: the Metacritic user score (0-10) x 10. Without that score there is no index
    (it is a tool to decide what to play next, so it does not use your personal score)."""
    if g.get("user_score") is not None:
        return float(g["user_score"]) * 10
    return None


def index_of(g):
    """
    Index = score (0-100) / square root of the hours.
    Higher score and fewer hours => higher index.
    Example: 90 pts in 10 h -> 28.5 | 90 pts in 100 h -> 9.0
    """
    b = base_score(g)
    h = g.get("hours")
    if b is None or not h or h <= 0:
        return None
    return b / math.sqrt(max(float(h), 1.0))


# --------------------------------------------------------------------------
# Automatic lookup (no API keys): HowLongToBeat + Steam + the public Metacritic page
# --------------------------------------------------------------------------
UA = {"User-Agent": "Mozilla/5.0 (compatible; MiBacklogJuegos)"}


def http_get(url, timeout=12):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def http_json(url, timeout=12):
    return json.loads(http_get(url, timeout).decode("utf-8", "replace"))


def _sim(a, b):
    return difflib.SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def platform_matches(mine, theirs):
    """Is the platform 'theirs' (the name on the website) the one you picked?"""
    return _norm(theirs) in PLATFORM_ALIASES.get(mine, {_norm(mine)})


def map_platforms(raw_names):
    """Website platform names -> yours (in PLATFORMS order)."""
    found, other = set(), False
    for raw in raw_names or []:
        raw = (raw or "").strip()
        if not raw:
            continue
        for mine in PLATFORMS:
            if mine != "Otra" and platform_matches(mine, raw):
                found.add(mine)
                break
        else:
            other = True
    out = [p for p in PLATFORMS if p in found]
    if other:
        out.append("Otra")
    return out


# ---- Metacritic: public game page ----
def metacritic_slug(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"['’]", "", s)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self):
        super().__init__()
        self.lines = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            t = " ".join(data.split())
            if t:
                self.lines.append(t)


# What Metacritic puts in ?platform=<slug> -> the app's platform name
METACRITIC_SLUGS = {
    "pc": "PC", "playstation-5": "PlayStation 5", "playstation-4": "PlayStation 4",
    "playstation-3": "PlayStation 3", "xbox-series-x": "Xbox Series X|S", "xbox-one": "Xbox One",
    "xbox-360": "Xbox 360", "nintendo-switch": "Nintendo Switch", "nintendo-switch-2": "Nintendo Switch 2",
    "nintendo-3ds": "Nintendo 3DS", "3ds": "Nintendo 3DS", "nintendo-ds": "Nintendo DS", "ds": "Nintendo DS",
}


def platform_of_slug(slug):
    if slug in METACRITIC_SLUGS:
        return METACRITIC_SLUGS[slug]
    return next((m for m in PLATFORMS if m != "Otra" and platform_matches(m, slug)), None)


class _PlatformTable(HTMLParser):
    """
    Reads the 'All Platforms' section of the HTML. Each platform is a link ...?platform=<slug> whose text is
    'Based on N Critic Reviews' + the score (or 'tbd'): the platform NAME is in the link, not in the
    visible text, so it cannot be found by proximity (that would pick up scores from individual reviews).
    """
    SKIP = {"script", "style", "noscript", "head"}

    def __init__(self):
        super().__init__()
        self.rows = []          # (slug, score or None, review count or None), in the order of the page
        self._skip = 0
        self._in_head = False
        self._in_section = False
        self._done = False
        self._href = None
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if self._skip:
            return
        if tag in ("h2", "h3"):
            self._in_head = True
            if self._in_section:
                self._done = True    # the next heading closes the section
        elif tag == "a":
            self._href = dict(attrs).get("href") or ""
            self._buf = []

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
            return
        if self._skip:
            return
        if tag in ("h2", "h3"):
            self._in_head = False
        elif tag == "a" and self._href is not None:
            if self._in_section and not self._done:
                self._take(self._href, " ".join(self._buf))
            self._href = None

    def handle_data(self, data):
        if self._skip:
            return
        t = " ".join(data.split())
        if not t:
            return
        if self._in_head and t.lower() == "all platforms":
            self._in_section = True
        if self._href is not None:
            self._buf.append(t)

    def _take(self, href, text):
        m = re.search(r"[?&]platform=([a-z0-9-]+)", href)
        if not m or any(r[0] == m.group(1) for r in self.rows):
            return
        n = re.search(r"based on ([\d.,]+) critic review", text, re.I)
        reviews = int(re.sub(r"\D", "", n.group(1)) or 0) if n else None
        words = re.sub(r"based on [\d.,]+ critic reviews?", "", text, flags=re.I).split()
        score = None
        if words and words[-1].isdigit() and 0 <= int(words[-1]) <= 100:
            score = int(words[-1])
        self.rows.append((m.group(1), score, reviews))


def parse_metacritic_platform_table(html):
    t = _PlatformTable()
    try:
        t.feed(html)
    except Exception:
        pass
    return t.rows


def metacritic_ld_platforms(html):
    """Game platforms according to the page's structured data (JSON-LD)."""
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            stack = [json.loads(m.group(1))]
        except Exception:
            continue
        while stack:
            d = stack.pop()
            if isinstance(d, dict):
                gp = d.get("gamePlatform")
                if isinstance(gp, str) and gp.strip():
                    return [gp.strip()]
                if isinstance(gp, list) and gp:
                    return [str(x).strip() for x in gp if str(x).strip()]
                stack.extend(d.values())
            elif isinstance(d, list):
                stack.extend(d)
    return []


def metacritic_page_score(html):
    """Global Metascore of the page: first its structured data (JSON-LD), otherwise the 'Metascore' label."""
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            stack = [json.loads(m.group(1))]
        except Exception:
            continue
        while stack:
            d = stack.pop()
            if isinstance(d, dict):
                ar = d.get("aggregateRating")
                if isinstance(ar, dict):
                    try:
                        v = int(float(ar.get("ratingValue")))
                        if 0 < v <= 100:
                            return v
                    except (TypeError, ValueError):
                        pass
                stack.extend(d.values())
            elif isinstance(d, list):
                stack.extend(d)
    ex = _TextExtractor()
    ex.feed(html)
    for i, l in enumerate(ex.lines):
        if l.lower() == "metascore":
            for l2 in ex.lines[i + 1:i + 4]:
                if re.fullmatch(r"\d{1,3}", l2) and 0 < int(l2) <= 100:
                    return int(l2)
            break
    return None


def metacritic_user_score(html):
    """
    User score (0-10) of the page: the number next to the 'User Score' label
    (it can be right after or right before it in the visible text). Returns None if it says 'tbd'
    or if Metacritic changes the page and it cannot be found.
    """
    ex = _TextExtractor()
    ex.feed(html)
    lines = ex.lines

    def as_score(s):
        if re.fullmatch(r"\d{1,2}(\.\d)?", s):
            v = float(s)
            if 0 < v <= 10:
                return v
        return None

    for i, l in enumerate(lines):
        if l.lower().rstrip(":") != "user score":
            continue
        for cand in lines[i + 1:i + 8] + list(reversed(lines[max(0, i - 3):i])):
            v = as_score(cand)
            if v is not None:
                return v
            if cand.lower() == "tbd":
                break
    return None


# ---- Metacritic reading: URL and page parsing
class MC:
    @staticmethod
    def url(name):
        return f"https://www.metacritic.com/game/{metacritic_slug(name)}/"

    @staticmethod
    def parse(html):
        return {"rows": parse_metacritic_platform_table(html), "ld_platforms": metacritic_ld_platforms(html),
                "page_score": metacritic_page_score(html), "user_score": metacritic_user_score(html)}


UPDATE_REPO = "madebydani/my-games-backlog"   # GitHub repository whose Releases the app updates from


# --------------------------------------------------------------------------
# App updates: the newest GitHub Release of the repository (Settings -> Check for updates)
# To publish a version: raise APP_VERSION, build the .exe, and create a Release with the tag v<APP_VERSION>
# and the .exe attached.
# --------------------------------------------------------------------------
APP_VERSION = "1.0.0"
RELEASES_API = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
SCRIPT_PATH = Path(__file__).resolve()   # this file (the Python version updates itself by replacing it)
# own process group: keeps running after the app closes. (Not DETACHED_PROCESS: with it PowerShell starts
# without a console and does nothing.) It is always combined with NO_WINDOW.
DETACHED = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def is_exe():
    return bool(getattr(sys, "frozen", False))


def parse_version(text):
    nums = [int(n) for n in re.findall(r"\d+", text or "")][:3]
    return tuple(nums + [0] * (3 - len(nums)))


def check_app_update():
    """Look at the newest Release on GitHub. Returns (result, info):
    'newer' / 'current' with {version, notes, page, exe, pyw}; 'none' if nothing is published; 'error'."""
    try:
        data = http_json(RELEASES_API, timeout=20)
    except urllib.error.HTTPError as e:
        return ("none", None) if e.code == 404 else ("error", f"HTTP {e.code}")
    except Exception as e:
        return "error", type(e).__name__
    tag = str(data.get("tag_name") or "")
    info = {"version": tag.lstrip("vV") or "?", "notes": (data.get("body") or "").strip(),
            "page": data.get("html_url"), "exe": None,
            "pyw": f"https://raw.githubusercontent.com/{UPDATE_REPO}/{urllib.parse.quote(tag)}/mi_backlog_juegos.pyw"}
    for a in data.get("assets") or []:
        if str(a.get("name") or "").lower().endswith(".exe"):
            info["exe"] = {"url": a.get("browser_download_url"), "size": a.get("size"), "digest": a.get("digest")}
            break
    newer = parse_version(info["version"]) > parse_version(APP_VERSION)
    return ("newer" if newer else "current"), info


def download_file(url, dest, progress=None, timeout=60):
    """Download url into dest. Returns (bytes, sha256). progress(done, total) is called while downloading."""
    req = urllib.request.Request(url, headers=UA)
    digest, done = hashlib.sha256(), 0
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    return done, digest.hexdigest()


def download_exe_update(info, progress=None):
    """Download the new .exe next to the current one (as '<name>.new'). Returns (True, path) or (False, reason)."""
    exe = Path(sys.executable)
    if (exe.parent / "_internal").is_dir():
        return False, "onedir"   # a folder build: replacing only the .exe would not be enough
    asset = info.get("exe")
    if not asset or not asset.get("url"):
        return False, "noexe"
    new = exe.with_name(exe.name + ".new")
    try:
        new.write_bytes(b"")   # can the folder be written to?
    except OSError:
        return False, "readonly"
    try:
        size, sha = download_file(asset["url"], new, progress)
        ok = size > 0 and (not asset.get("size") or size == asset["size"])
        ok = ok and new.read_bytes()[:2] == b"MZ"   # a Windows program
        d = str(asset.get("digest") or "")
        if d.startswith("sha256:"):
            ok = ok and d[7:].lower() == sha
        if not ok:
            new.unlink(missing_ok=True)
            return False, "corrupt"
    except Exception as e:
        new.unlink(missing_ok=True)
        return False, type(e).__name__
    return True, new


def start_exe_swap(exe, new, pid):
    """When this process (pid) has closed, put the new .exe in place of the old one and open it.
    It is done by a small PowerShell script, because a running .exe cannot replace itself."""
    def q(path):
        return "'" + str(path).replace("'", "''") + "'"
    script = Path(os.environ.get("TEMP") or exe.parent) / f"my_game_backlog_update_{pid}.ps1"
    script.write_text(f"""$ErrorActionPreference = 'SilentlyContinue'
Wait-Process -Id {pid} -Timeout 120
Start-Sleep -Milliseconds 700
for ($i = 0; $i -lt 30; $i++) {{
    try {{ Move-Item -LiteralPath {q(new)} -Destination {q(exe)} -Force -ErrorAction Stop; break }}
    catch {{ Start-Sleep -Milliseconds 500 }}
}}
Start-Process -FilePath {q(exe)}
Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force
""", encoding="utf-8-sig")
    subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                      "-File", str(script)], creationflags=DETACHED | NO_WINDOW, close_fds=True)
    return script


def install_pyw_update(info):
    """Python version: replace this file with the one of the new version (a copy of the old one is kept)."""
    try:
        data = http_get(info["pyw"], timeout=60)
        text = data.decode("utf-8")
        compile(text, str(SCRIPT_PATH), "exec")   # it must be valid Python
        if "APP_VERSION" not in text or "class MainWindow" not in text:
            return False, "corrupt"
    except Exception as e:
        return False, type(e).__name__
    try:
        shutil.copy2(SCRIPT_PATH, SCRIPT_PATH.with_name(SCRIPT_PATH.name + ".bak"))
        SCRIPT_PATH.write_bytes(data)
    except OSError:
        return False, "readonly"
    return True, SCRIPT_PATH


def metacritic_lookup(name):
    """(scores by platform, platforms seen, user score, number of reviews by platform)."""
    html = http_get(MC.url(name)).decode("utf-8", "replace")
    raw = MC.parse(html)
    scores, counts, seen = {}, {}, []
    rows = raw.get("rows") or []
    for slug, score, n in rows:
        seen.append(slug)
        mine = platform_of_slug(slug)
        if mine and mine not in scores:
            scores[mine] = score
            counts[mine] = n or 0
    if not rows:
        # no 'All Platforms' table (single-platform game, or Metacritic changed the page)
        seen = raw.get("ld_platforms") or []
        page = raw.get("page_score")
        mines = [m for m in PLATFORMS if m != "Otra" and any(platform_matches(m, x) for x in seen)]
        if page is not None:
            if len(seen) == 1 and mines:
                scores[mines[0]] = page       # exclusive: the global score is the one of its only platform
            else:
                scores[""] = page             # page score with no way to tell which platform it belongs to
    return scores, seen, raw.get("user_score"), counts


# If Metacritic has no score for your platform, its 'sibling' is tried first (backward-compatible games)
META_FALLBACKS = {
    "PlayStation 5": ["PlayStation 4"], "PlayStation 4": ["PlayStation 5"],
    "Xbox Series X|S": ["Xbox One"], "Xbox One": ["Xbox Series X|S"],
    "Nintendo Switch 2": ["Nintendo Switch"], "Nintendo Switch": ["Nintendo Switch 2"],
    "Nintendo 3DS": ["Nintendo DS"], "Nintendo DS": ["Nintendo 3DS"],
}


def choose_metacritic(platform, scores, counts, steam_meta):
    """
    Pick the Metacritic score. Returns (score, platform the score belongs to, is it from another platform?).
    With a chosen platform: its own; if there is none, its sibling's (PS5 -> PS4...), then PC and finally
    the platform with the most reviews. The third value is True whenever it is NOT the chosen platform's score.
    """
    have = {p: v for p, v in scores.items() if p and v is not None}
    if steam_meta and "PC" not in have:
        have["PC"] = steam_meta
    if not platform:
        first = next(iter(have.items()), None)
        if first:
            return first[1], first[0], False
        return (scores[""], "", False) if scores.get("") is not None else (None, None, False)
    if platform in have:
        return have[platform], platform, False
    if scores.get("") is not None:
        return scores[""], "", True
    order = [p for p in META_FALLBACKS.get(platform, []) if p in have]
    if "PC" in have and "PC" not in order:
        order.append("PC")
    order += sorted((p for p in have if p not in order), key=lambda p: -(counts.get(p) or 0))
    if order:
        return have[order[0]], order[0], True
    return None, None, False


# ---- Steam ----
def steam_lookup(name, steam_id=None, want_cover=True):
    """(appid, name, cover art as bytes, PC Metacritic score) or None. Steam's score is the PC one."""
    appid, found = steam_id, None
    if not appid:
        q = urllib.parse.quote(name)
        data = http_json(f"https://store.steampowered.com/api/storesearch/?term={q}&l=english&cc=US")
        items = [i for i in data.get("items", []) if i.get("type", "app") == "app"]
        if not items:
            return None
        best = max(items, key=lambda i: _sim(name, i["name"]))
        if _sim(name, best["name"]) < 0.5:
            return None
        appid, found = best["id"], best["name"]
    cover = None
    if want_cover:
        for suffix in ("library_600x900.jpg", "header.jpg"):
            try:
                cover = http_get(f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/{suffix}")
                break
            except Exception:
                continue
    meta = None
    try:
        det = http_json(f"https://store.steampowered.com/api/appdetails?appids={appid}&l=english")
        mc = det.get(str(appid), {}).get("data", {}).get("metacritic")
        if mc and mc.get("score"):
            meta = int(mc["score"])
    except Exception:
        pass
    return appid, found, cover, meta


# ---- HowLongToBeat ----
def _hltb_platforms(r):
    raw = getattr(r, "profile_platforms", None)
    if raw is None:
        raw = (getattr(r, "json_content", None) or {}).get("profile_platform")
    if isinstance(raw, str):
        return [x.strip() for x in raw.split(",") if x.strip()]
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    return []


def fetch_game_info(name, platform="", pick=None, meta_only=False, with_cover=True):
    """
    Look up canonical name, cover art, hours, game platforms and Metacritic score.
    If a platform was chosen, the score is the one for THAT platform.
    `pick` is a suggestion chosen from the list and `meta_only` only recomputes the score
    (when the platform changes).
    """
    info = {"name": None, "cover": None, "meta": None, "meta_platform": None,
            "hours": None, "platforms": [], "log": [],
            "hours_main": None, "hours_extra": None, "hours_100": None, "hltb_found": False, "platform": "", "user": None,
            "meta_notice": None}
    pick = pick or {}
    pc_like = platform in ("", "PC")
    raw_platforms = []
    hltb_cover_url = None

    # 1) HowLongToBeat: name, hours and platforms
    if not meta_only:
        try:
            from howlongtobeatpy import HowLongToBeat
            res = HowLongToBeat().search(pick.get("name") or name) or []
            best = None
            if pick.get("hltb_id"):
                best = next((r for r in res if str(r.game_id) == str(pick["hltb_id"])), None)
            if best is None and res:
                best = max(res, key=lambda r: r.similarity)
                if best.similarity < 0.5:
                    best = None
            if best:
                info["name"] = best.game_name
                def _h(attr):
                    try:
                        v = float(getattr(best, attr, None) or 0)
                    except (TypeError, ValueError):
                        return None
                    return round(v, 1) if v > 0 else None
                info["hltb_found"] = True
                info["hours_main"], info["hours_extra"], info["hours_100"] = (
                    _h("main_story"), _h("main_extra"), _h("completionist"))
                # index hours = HLTB's default figure (average of all play styles)
                info["hours"] = _h("all_styles") or info["hours_extra"] or info["hours_main"] or info["hours_100"]
                if not info["hours"]:
                    info["log"].append(tr("HowLongToBeat: no hours found"))
                raw_platforms += _hltb_platforms(best)
                hltb_cover_url = getattr(best, "game_image_url", None)
            else:
                info["log"].append(tr("HowLongToBeat: game not found"))
        except ImportError:
            info["log"].append(tr("Missing 'howlongtobeatpy' (pip install howlongtobeatpy): no hours or platforms"))
        except Exception as e:
            info["log"].append(tr("HowLongToBeat did not respond ({err})", err=type(e).__name__))

    canon = info["name"] or pick.get("name") or name

    # 2) Steam: vertical cover art and, for PC, the Metacritic score
    steam = None
    if (not meta_only) or pc_like:
        try:
            steam = steam_lookup(canon, pick.get("steam_id"), want_cover=with_cover and not meta_only)
        except Exception as e:
            info["log"].append(tr("Steam did not respond ({err})", err=type(e).__name__))
    steam_meta = None
    if steam:
        _, sname, scover, steam_meta = steam
        if not info["name"]:
            info["name"] = sname or pick.get("name")
        if scover:
            info["cover"] = scover
    if with_cover and not meta_only and info["cover"] is None and hltb_cover_url:
        try:
            info["cover"] = http_get(hltb_cover_url)
        except Exception:
            pass
    if with_cover and not meta_only and info["cover"] is None:
        info["log"].append(tr("No cover found automatically (choose or paste one yourself)"))

    # 3) Metacritic: public page (scores by platform and the game's platforms)
    scores, seen, user, counts = {}, [], None, {}
    try:
        scores, seen, user, counts = metacritic_lookup(canon)
        if not seen and not scores:
            info["log"].append(tr("Metacritic: could not read the page (use “Open Metacritic” and enter the score by hand)"))
    except urllib.error.HTTPError as e:
        info["log"].append(tr("Metacritic: title page not found") if e.code == 404
                           else tr("Metacritic responded with error {code}", code=e.code))
    except Exception as e:
        info["log"].append(tr("Metacritic did not respond ({err})", err=type(e).__name__))
    info["user"] = user
    raw_platforms += seen
    if raw_platforms and steam:
        raw_platforms.append("PC")  # Steam only confirms PC; it is not used to trim the list

    meta, meta_plat, other = choose_metacritic(platform, scores, counts, steam_meta)
    if meta is not None:
        info["meta"], info["meta_platform"] = meta, (meta_plat or platform or None)
        if other:
            # the score is NOT from the chosen platform: it is still filled in, but with a warning
            if meta_plat:
                notice = tr("⚠ Metacritic has no score for {platform}: using the one from {used} ({score}). "
                            "Check it, or choose the right platform or type the score by hand.",
                            platform=PLATFORM_SHORT.get(platform, platform),
                            used=PLATFORM_SHORT.get(meta_plat, meta_plat), score=meta)
            else:
                notice = tr("⚠ Metacritic does not list scores by platform for this game: using its general "
                            "score ({score}). Check it.", score=meta)
            info["meta_notice"] = notice
            info["log"].append(notice)
    elif platform and (seen or scores):
        con_nota = [PLATFORM_SHORT.get(p, p) for p, v in scores.items() if p and v is not None]
        info["log"].append(tr("Metacritic has no score for {platform}", platform=platform)
                           + (tr(" (it does for: {names})", names=", ".join(con_nota)) if con_nota else ""))
    if not platform:
        # default platform: the one the score comes from; otherwise the first available
        avail = map_platforms(raw_platforms)
        if info["meta_platform"] and (not avail or info["meta_platform"] in avail):
            info["platform"] = info["meta_platform"]
        elif avail:
            info["platform"] = avail[0]
    if info["meta"] is None and not any("Metacritic" in l for l in info["log"]):
        info["log"].append(tr("Metacritic: no score"))

    info["platforms"] = map_platforms(raw_platforms)
    return info




# --------------------------------------------------------------------------
# Text utilities
# --------------------------------------------------------------------------
@functools.lru_cache(maxsize=8192)
def _fold(s):
    """Lowercase, no accents or symbols: 'Pokémon: Escarlata' -> 'pokemon escarlata'."""
    s = unicodedata.normalize("NFKD", s or "").lower()
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w]+", " ", s).split())


def _rank(text, name):
    """Score used to sort suggestions: starts with the typed text > contains it > looks similar."""
    t, n = _fold(text), _fold(name)
    if not t or not n:
        return 0.0
    score = difflib.SequenceMatcher(None, t, n).ratio()
    if n.startswith(t):
        score += 0.6
    elif t in n:
        score += 0.4
    return score


def AL(*flags):
    """Join alignment flags into one integer (what QPainter.drawText expects in PyQt6)."""
    v = 0
    for f in flags:
        v |= f.value
    return v


A_CENTER = AL(Qt.AlignmentFlag.AlignCenter)
A_LEFT = AL(Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignVCenter)
A_RIGHT = AL(Qt.AlignmentFlag.AlignRight, Qt.AlignmentFlag.AlignVCenter)


# --------------------------------------------------------------------------
# Name suggestions (fast: in parallel, with partial results and a cache)
# --------------------------------------------------------------------------
SUG_TIMEOUT = 6  # seconds per request


def steam_suggest(q):
    data = http_json("https://store.steampowered.com/api/storesearch/"
                     f"?term={urllib.parse.quote(q)}&l=english&cc=US", timeout=SUG_TIMEOUT)
    return [{"name": i["name"], "steam_id": i["id"]}
            for i in data.get("items", [])[:8] if i.get("type", "app") == "app"]


def hltb_suggest(q):
    from howlongtobeatpy import HowLongToBeat
    return [{"name": r.game_name, "hltb_id": r.game_id, "platforms": _hltb_platforms(r)}
            for r in (HowLongToBeat().search(q) or [])[:8]]


def _merge_item(items, name, hltb_id=None, steam_id=None, platforms=()):
    k = _norm(name)
    if not k:
        return
    d = items.setdefault(k, {"name": name, "hltb_id": None, "steam_id": None, "platforms": []})
    if hltb_id:
        d["hltb_id"] = hltb_id
    if steam_id:
        d["steam_id"] = steam_id
    for p in platforms:
        if p not in d["platforms"]:
            d["platforms"].append(p)


def _ranked(items, text):
    return sorted(items.values(), key=lambda d: _rank(text, d["name"]), reverse=True)[:10]


def loosened_queries(text):
    """Looser variants of the text, to find the game even with a typo."""
    t = text.strip()
    out = []
    if len(t) > 4:
        out.append(t[:-1])
    if len(t) > 5:
        out.append(t[:-2])
    words = t.split()
    if len(words) > 1:
        out.append(words[0])
    if len(t) > 6:
        out.append(t[: len(t) // 2 + 1])
    seen, res = {t.lower()}, []
    for q in out:
        if len(q) >= 3 and q.lower() not in seen:
            seen.add(q.lower())
            res.append(q)
    return res


_SUG_CACHE = {}


def _spawn(fn, arg, out):
    """Run fn(arg) in a daemon thread and leave the result (or []) in the queue."""
    def run():
        try:
            out.put(fn(arg))
        except Exception:
            out.put([])
    threading.Thread(target=run, daemon=True).start()


def suggest_job(token, text, is_current, emit):
    """
    Runs in a thread. Launches Steam and HowLongToBeat AT THE SAME TIME and emits whatever
    arrives (Steam usually answers in a fraction of a second; there is no need to wait for HLTB).
    Only if the result is poor (typo) does it try text variants, also in parallel.
    """
    try:
        key = _fold(text)
        if key in _SUG_CACHE:
            emit(token, _SUG_CACHE[key], True)
            return
        items = {}

        def gather(queries):
            out = queue.Queue()
            n = 0
            for q in queries:
                for fn in (steam_suggest, hltb_suggest):
                    _spawn(fn, q, out)
                    n += 1
            for _ in range(n):
                try:
                    res = out.get(timeout=SUG_TIMEOUT + 4)
                except queue.Empty:
                    break
                for r in res:
                    _merge_item(items, **r)
                if not is_current():
                    return False
                if items:
                    emit(token, _ranked(items, text), False)
            return True

        if not gather([text]):
            return
        poor = len(items) < 3 or max((_rank(text, d["name"]) for d in items.values()), default=0) < 0.8
        if poor:
            variants = loosened_queries(text)[:3]
            if variants and not gather(variants):
                return
        final = _ranked(items, text)
        if final:
            _SUG_CACHE[key] = final
        emit(token, final, True)
    except Exception:
        try:
            emit(token, [], True)
        except Exception:
            pass


# --------------------------------------------------------------------------
# Updating the connections with the websites
# HowLongToBeat is read through the 'howlongtobeatpy' library, which its author updates when the website
# changes: the app can install the newest version by itself. (Metacritic is read by code inside this file.)
# --------------------------------------------------------------------------
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # no black console window on Windows


def _python_cmd():
    """The Python that runs the app (python.exe rather than pythonw.exe, so pip can report back)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        exe = exe.with_name("python.exe")
    return str(exe)


def installed_version(package):
    try:
        out = subprocess.run([_python_cmd(), "-c", f"import importlib.metadata as m; print(m.version({package!r}))"],
                             capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW)
        return out.stdout.strip() or None
    except Exception:
        return None


def update_hltb_library():
    """Install the newest 'howlongtobeatpy' with pip. Returns (version before, version after, error or None)."""
    old = installed_version("howlongtobeatpy")
    try:
        r = subprocess.run([_python_cmd(), "-m", "pip", "install", "--upgrade", "--disable-pip-version-check",
                            "howlongtobeatpy"], capture_output=True, text=True, timeout=600, creationflags=NO_WINDOW)
    except Exception as e:
        return old, old, f"{type(e).__name__}: {e}"
    new = installed_version("howlongtobeatpy")
    if r.returncode != 0:
        lines = (r.stderr or r.stdout or "").strip().splitlines()
        return old, new, "\n".join(lines[-4:]) or f"pip exit code {r.returncode}"
    return old, new, None


class Bridge(QObject):
    """Thread -> UI bridge: signals emitted from Python threads reach the main thread."""
    suggestions = pyqtSignal(int, object, bool)   # token, list, is it the final result?
    info = pyqtSignal(object, bool, bool)          # info, overwrite, meta_only
    cover = pyqtSignal(object)                     # image bytes downloaded from a dropped link (or None)
    task = pyqtSignal(object)                      # progress / result of a background task of the main window


# --------------------------------------------------------------------------
# Look and feel
# --------------------------------------------------------------------------
ACCENT, ACCENT_HI, ACCENT_LO = "#7c5cff", "#9378ff", "#6445ee"

# Themes: every color of the interface comes from here. "dark" is the original look.
THEMES = {
    "dark": {
        "BG": "#0e1018", "SURFACE": "#141725", "SURFACE2": "#1a1e2f", "SURFACE3": "#222740",
        "BORDER": "#272c43", "BORDER_HI": "#3a4263", "TEXT": "#e9ebf5", "MUTED": "#838ba9", "CARD": "#171b2a",
        "TITLE": "#ffffff", "PLACEHOLDER": "#6b7392",
        "BTN_HOVER": "#2a3050", "BTN_PRESSED": "#1d2239", "BTN_DIS_BG": "#181c2c", "BTN_DIS_BORDER": "#20253a",
        "BTN_DIS_TEXT": "#596082", "PRIMARY_DIS_BG": "#2b2750", "PRIMARY_DIS_TEXT": "#7b7aa3",
        "SOFT_TEXT": "#d3c9ff", "GHOST_HOVER": "#1c2136", "DANGER_TEXT": "#ff9d9d",
        "SCROLL": "#2b3150", "SCROLL_HI": "#3d4670",
        "COVER_EMPTY": "#232840", "COVER_EMPTY_ICON": "#4b5373", "CARD_TITLE": "#f1f3fa", "CARD_LABEL": "#79809f",
        "CARD_VALUE": "#c9ccdd", "BAR": "#242942", "BAR_LABEL": "#9aa1c0", "CARD_SUB": "#8d94b3",
        "INDEX": "#b9a6ff", "NONE": "#5b6283", "WARN": "#f0b429", "DIVIDER": (255, 255, 255, 18),
        "SCORE_HI": "#3ecf6e", "SCORE_MID": "#f2c94c", "SCORE_LO": "#ef5b5b", "SCORE_NONE": "#6b7390",
        "STATUS_TEXT": True,   # the status filters are written in their own color
        "CARD_TINT": 1.0,      # how much the card background takes the status color (1 = as always)
        "CARD_EDGE": (190, 2.0, 3.0),   # status border: opacity, width, width on hover
    },
    "black": {   # pure black (good on OLED screens)
        "BG": "#000000", "SURFACE": "#080808", "SURFACE2": "#111111", "SURFACE3": "#1a1a1a",
        "BORDER": "#222222", "BORDER_HI": "#363636", "TEXT": "#ececec", "MUTED": "#8a8a8a", "CARD": "#0b0b0b",
        "TITLE": "#ffffff", "PLACEHOLDER": "#666666",
        "BTN_HOVER": "#262626", "BTN_PRESSED": "#141414", "BTN_DIS_BG": "#0d0d0d", "BTN_DIS_BORDER": "#1c1c1c",
        "BTN_DIS_TEXT": "#555555", "PRIMARY_DIS_BG": "#2b2750", "PRIMARY_DIS_TEXT": "#7b7aa3",
        "SOFT_TEXT": "#d3c9ff", "GHOST_HOVER": "#161616", "DANGER_TEXT": "#ff9d9d",
        "SCROLL": "#2a2a2a", "SCROLL_HI": "#444444",
        "COVER_EMPTY": "#161616", "COVER_EMPTY_ICON": "#444444", "CARD_TITLE": "#f5f5f5", "CARD_LABEL": "#7a7a7a",
        "CARD_VALUE": "#d0d0d0", "BAR": "#161616", "BAR_LABEL": "#9a9a9a", "CARD_SUB": "#8f8f8f",
        "INDEX": "#b9a6ff", "NONE": "#555555", "WARN": "#f0b429", "DIVIDER": (255, 255, 255, 22),
        "SCORE_HI": "#3ecf6e", "SCORE_MID": "#f2c94c", "SCORE_LO": "#ef5b5b", "SCORE_NONE": "#666666",
        "STATUS_TEXT": True,
        "CARD_TINT": 1.0,
        "CARD_EDGE": (190, 2.0, 3.0),
    },
    "light": {
        "BG": "#eef0f5", "SURFACE": "#ffffff", "SURFACE2": "#f7f8fb", "SURFACE3": "#eceef5",
        "BORDER": "#dde0ea", "BORDER_HI": "#c4c9da", "TEXT": "#1d2030", "MUTED": "#6b7088", "CARD": "#ffffff",
        "TITLE": "#11131c", "PLACEHOLDER": "#9aa0b5",
        "BTN_HOVER": "#e2e5f0", "BTN_PRESSED": "#d6dae8", "BTN_DIS_BG": "#f0f1f5", "BTN_DIS_BORDER": "#e3e5ec",
        "BTN_DIS_TEXT": "#a4a9bb", "PRIMARY_DIS_BG": "#d9d1ff", "PRIMARY_DIS_TEXT": "#8f86c4",
        "SOFT_TEXT": "#5536d6", "GHOST_HOVER": "#eceef5", "DANGER_TEXT": "#c93a3a",
        "SCROLL": "#c9cdda", "SCROLL_HI": "#a9afc3",
        "COVER_EMPTY": "#e6e8f0", "COVER_EMPTY_ICON": "#a4a9bb", "CARD_TITLE": "#151826", "CARD_LABEL": "#7b8098",
        "CARD_VALUE": "#3a3f55", "BAR": "#f0f1f6", "BAR_LABEL": "#646a83", "CARD_SUB": "#6b7088",
        "INDEX": "#6d4aff", "NONE": "#b3b7c6", "WARN": "#d97706", "DIVIDER": (0, 0, 0, 22),
        "SCORE_HI": "#16a34a", "SCORE_MID": "#d97706", "SCORE_LO": "#dc2626", "SCORE_NONE": "#a4a9bb",
        "STATUS_TEXT": False,   # yellow / light text is hard to read on white: the labels stay dark
        "CARD_TINT": 0.0,       # white cards: on white, the status tint turned into pastel greens / yellows / reds
        "CARD_EDGE": (150, 1.5, 2.5),   # thinner status border; the status pill already says it
    },
}
THEME_NAMES = [("dark", "Dark"), ("black", "Black"), ("light", "Light")]
THEME = "dark"
TH = dict(THEMES["dark"])
BG = SURFACE = SURFACE2 = SURFACE3 = BORDER = BORDER_HI = TEXT = MUTED = CARD = ""


def set_theme(code):
    """Choose the colors of the interface (they are read every time something is drawn)."""
    global THEME, BG, SURFACE, SURFACE2, SURFACE3, BORDER, BORDER_HI, TEXT, MUTED, CARD
    THEME = code if code in THEMES else "dark"
    TH.clear()
    TH.update(THEMES[THEME])
    BG, SURFACE, SURFACE2, SURFACE3 = TH["BG"], TH["SURFACE"], TH["SURFACE2"], TH["SURFACE3"]
    BORDER, BORDER_HI, TEXT, MUTED, CARD = TH["BORDER"], TH["BORDER_HI"], TH["TEXT"], TH["MUTED"], TH["CARD"]


set_theme("dark")

ASSETS = {}  # paths of the small icons drawn at startup (arrow, checks)


def make_pixmap(w, h, draw, dpr=1):
    pm = QPixmap(int(w * dpr), int(h * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw(p)
    p.end()
    return pm


def _stroke(p, color, width):
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)


def build_assets():
    """Draw the small icons the style sheet needs. If anything fails, the app keeps working without them."""
    out = {}
    try:
        d = DATA_DIR / "assets"
        d.mkdir(parents=True, exist_ok=True)

        def chevron(p):
            _stroke(p, MUTED, 1.8)
            path = QPainterPath()
            path.moveTo(3.5, 5.5)
            path.lineTo(7, 9)
            path.lineTo(10.5, 5.5)
            p.drawPath(path)

        def check(color):
            def draw(p):
                _stroke(p, color, 2.2)
                path = QPainterPath()
                path.moveTo(3, 7.5)
                path.lineTo(6, 10.5)
                path.lineTo(11, 3.8)
                p.drawPath(path)
            return draw

        for name, draw in (("arrow_down", chevron), ("check_white", check("#ffffff")),
                           ("check_dark", check("#10121b"))):
            path = d / f"{name}_{THEME}.png"
            if make_pixmap(14, 14, draw).save(str(path), "PNG"):
                out[name] = path.as_posix()
    except Exception:
        pass
    return out


def app_icon():
    """App icon (game controller on a purple background), drawn in code."""
    def draw(p):
        g = QLinearGradient(0, 0, 0, 256)
        g.setColorAt(0, QColor(ACCENT_HI))
        g.setColorAt(1, QColor(ACCENT_LO))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(QRectF(8, 8, 240, 240), 56, 56)
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(QRectF(44, 88, 168, 96), 48, 48)
        p.setBrush(QColor(ACCENT_LO))
        p.drawRoundedRect(QRectF(70, 126, 44, 12), 5, 5)     # d-pad
        p.drawRoundedRect(QRectF(86, 110, 12, 44), 5, 5)
        p.drawEllipse(QRectF(148, 114, 20, 20))              # buttons
        p.drawEllipse(QRectF(170, 134, 20, 20))
    return QIcon(make_pixmap(256, 256, draw))


def search_icon():
    def draw(p):
        _stroke(p, MUTED, 1.8)
        p.drawEllipse(QRectF(3, 3, 9, 9))
        p.drawLine(11, 11, 15, 15)
    return QIcon(make_pixmap(18, 18, draw, dpr=2))


def build_palette():
    pal = QPalette()
    R = QPalette.ColorRole
    for role, col in (
        (R.Window, BG), (R.WindowText, TEXT), (R.Base, SURFACE2), (R.AlternateBase, SURFACE),
        (R.Text, TEXT), (R.Button, SURFACE3), (R.ButtonText, TEXT), (R.ToolTipBase, SURFACE2),
        (R.ToolTipText, TEXT), (R.Highlight, ACCENT), (R.HighlightedText, "#ffffff"),
        (R.PlaceholderText, TH["PLACEHOLDER"]),
    ):
        pal.setColor(role, QColor(col))
    return pal


STYLE_TEMPLATE = """
QWidget { font-family: "Segoe UI Variable Text", "Segoe UI", "SF Pro Text", "Helvetica Neue", "Noto Sans", Arial, sans-serif;
          font-size: 13px; color: @TEXT@; }
QMainWindow { background: @BG@; }
QDialog, QMessageBox { background: @SURFACE@; }
QLabel, QCheckBox { background: transparent; }
QToolTip { background: @SURFACE2@; color: @TEXT@; border: 1px solid @BORDER_HI@; padding: 6px 8px; }

/* text */
#sidebar { background: @SURFACE@; border-right: 1px solid @BORDER@; }
#title { font-size: 22px; font-weight: 700; color: @TITLE@; }
#subtitle, #hint { color: @MUTED@; font-size: 12px; }
#section { color: @MUTED@; font-size: 12px; font-weight: 600; margin-top: 8px; }
#fieldLabel { color: @MUTED@; font-size: 12px; font-weight: 600; }
#stats { color: @MUTED@; padding: 6px 2px; }
#noticeBar { background: @SURFACE2@; border: 1px solid @BORDER_HI@; border-radius: 12px; }
#empty { color: @MUTED@; font-size: 15px; }
#indexPreview { color: @SOFT_TEXT@; font-size: 14px; font-weight: 700; background: rgba(124, 92, 255, 34);
                border: 1px solid rgba(124, 92, 255, 90); border-radius: 10px; padding: 9px 14px; }
#coverPreview { background: @SURFACE2@; border: 1px solid @BORDER@; border-radius: 14px; color: @MUTED@; }

/* text fields, numbers and dropdowns: fixed height so the text is never cut off */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: @SURFACE2@; border: 1px solid @BORDER@; border-radius: 10px;
    padding: 0 12px; min-height: 38px; selection-background-color: @ACCENT@; selection-color: #ffffff;
}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover { border-color: @BORDER_HI@; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QComboBox:on { border: 1px solid @ACCENT@; }
/* the text field inside each spinbox must NOT inherit border, padding or height (it clipped the text) */
QSpinBox QLineEdit, QDoubleSpinBox QLineEdit, QAbstractSpinBox QLineEdit {
    background: transparent; border: none; border-radius: 0; padding: 0; margin: 0; min-height: 0; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 30px; border: none; }
QComboBox QAbstractItemView { background: @SURFACE2@; border: 1px solid @BORDER_HI@; padding: 4px; outline: 0;
                              selection-background-color: @ACCENT@; selection-color: #ffffff; }
QComboBox QAbstractItemView::item { min-height: 30px; padding: 0 8px; }

/* suggestion list while typing the name */
#suggestPopup { background: @SURFACE2@; border: 1px solid @BORDER_HI@; padding: 4px; outline: 0;
                selection-background-color: @ACCENT@; selection-color: #ffffff; }
#suggestPopup::item { min-height: 32px; padding: 0 10px; }

/* checkboxes */
QCheckBox { spacing: 10px; padding: 3px 0; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 6px; border: 2px solid @BORDER_HI@; background: transparent; }
QCheckBox::indicator:hover { border-color: @ACCENT@; }
QCheckBox::indicator:checked { background: @ACCENT@; border-color: @ACCENT@; }

/* buttons */
QPushButton { background: @SURFACE3@; border: 1px solid @BORDER@; border-radius: 10px; padding: 0 16px;
              min-height: 38px; font-weight: 600; color: @TEXT@; }
QPushButton:hover { background: @BTN_HOVER@; border-color: @BORDER_HI@; }
QPushButton:pressed { background: @BTN_PRESSED@; }
QPushButton:focus { border-color: @ACCENT@; }
QPushButton:disabled { background: @BTN_DIS_BG@; border-color: @BTN_DIS_BORDER@; color: @BTN_DIS_TEXT@; }

QPushButton#primary { color: #ffffff; font-weight: 700; padding: 0 22px; border: 1px solid @ACCENT_LO@;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 @ACCENT_HI@, stop:1 @ACCENT_LO@); }
QPushButton#primary:hover { border-color: @ACCENT_HI@;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #a68fff, stop:1 #7355f5); }
QPushButton#primary:pressed { background: @ACCENT_LO@; }
QPushButton#primary:disabled { background: @PRIMARY_DIS_BG@; border-color: @PRIMARY_DIS_BG@; color: @PRIMARY_DIS_TEXT@; }

QPushButton#soft { background: rgba(124, 92, 255, 38); border: 1px solid rgba(124, 92, 255, 110); color: @SOFT_TEXT@; }
QPushButton#soft:hover { background: rgba(124, 92, 255, 70); border-color: @ACCENT@; }
QPushButton#soft:disabled { background: @BTN_DIS_BG@; border-color: @BTN_DIS_BORDER@; color: @BTN_DIS_TEXT@; }

QPushButton#ghost { background: transparent; border: 1px solid @BORDER_HI@; }
QPushButton#ghost:hover { background: @GHOST_HOVER@; }
QPushButton#ghost:checked { background: rgba(124, 92, 255, 70); border: 1px solid @ACCENT@; }

QPushButton#danger { background: rgba(239, 91, 91, 40); border: 1px solid rgba(239, 91, 91, 120); color: @DANGER_TEXT@; }
QPushButton#danger:hover { background: rgba(239, 91, 91, 75); }

QMessageBox QPushButton { min-width: 96px; }

/* card list and scroll bars */
QListWidget { background: transparent; border: none; outline: 0; }
QListWidget::item, QListWidget::item:selected, QListWidget::item:hover { background: transparent; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: @SCROLL@; border-radius: 4px; min-height: 40px; }
QScrollBar::handle:vertical:hover { background: @SCROLL_HI@; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

/* tier list */
#tierDialog { background: @BG@; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QSplitter::handle:vertical { height: 10px; background: transparent; }
QSplitter::handle:vertical:hover { background: @BORDER_HI@; border-radius: 3px; }
#tierRow { background: @SURFACE2@; border: 1px solid @BORDER@; border-radius: 10px; }
QPushButton#tierCtl { padding: 0px; min-height: 0px; min-width: 0px; font-size: 13px; border-radius: 8px; }
QPushButton#tierCtl:disabled { color: @BORDER@; }

/* sidebar: scroll area, draggable splitter, tier list preview and view buttons */
#sideScroll, #sideScroll > QWidget, #sideScroll > QWidget > QWidget { background: transparent; border: none; }
QSplitter::handle:horizontal { background: transparent; }
QSplitter::handle:horizontal:hover { background: @BORDER_HI@; }
#tierPreview { background: @SURFACE2@; border: 1px solid @BORDER@; border-radius: 10px; color: @MUTED@; font-size: 12px; }
QPushButton#seg { padding: 0px; }
QPushButton#seg:checked { background: rgba(124, 92, 255, 70); border-color: @ACCENT@; }

/* context menu */
QMenu { background: @SURFACE2@; border: 1px solid @BORDER_HI@; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 8px 26px 8px 14px; border-radius: 6px; margin: 1px 0; }
QMenu::item:selected { background: @ACCENT@; color: #ffffff; }
QMenu::separator { height: 1px; background: @BORDER@; margin: 6px 8px; }
"""

def build_style(assets):
    css = STYLE_TEMPLATE
    tokens = dict(TH, ACCENT=ACCENT, ACCENT_HI=ACCENT_HI, ACCENT_LO=ACCENT_LO)
    for k, v in tokens.items():
        if isinstance(v, str):
            css = css.replace(f"@{k}@", v)
    if assets.get("arrow_down"):
        css += 'QComboBox::down-arrow { image: url("%s"); width: 14px; height: 14px; }\n' % assets["arrow_down"]
    if assets.get("check_white"):
        css += ('QCheckBox::indicator:checked { background: %s; border-color: %s; image: url("%s"); }\n'
                % (ACCENT, ACCENT, assets["check_white"]))
    return css


# ---- widget builders with the app's look ----
def make_btn(text, name="", tip=""):
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFocusPolicy(Qt.FocusPolicy.TabFocus)   # the focus ring only shows when navigating with Tab
    return b


def make_combo():
    c = QComboBox()
    c.setItemDelegate(QStyledItemDelegate(c))   # needed so the QSS can style the dropdown items
    c.setMaxVisibleItems(12)
    c.setCursor(Qt.CursorShape.PointingHandCursor)
    return c


class NumField(QLineEdit):
    """Numeric field built on QLineEdit (styled QSpinBoxes leave no room for the text).
    Empty = no data (value() returns 0). Accepts a comma or a dot as the decimal separator."""
    valueChanged = pyqtSignal(float)

    def __init__(self, lo, hi, decimals=0, placeholder="—"):
        super().__init__()
        self.lo, self.hi, self.dec = lo, hi, decimals
        self.setPlaceholderText(placeholder)
        rx = r"[0-9]{0,4}" if not decimals else r"[0-9]{0,4}[.,]?[0-9]{0,%d}" % decimals
        self.setValidator(QRegularExpressionValidator(QRegularExpression(rx), self))
        self.textChanged.connect(lambda _t: self.valueChanged.emit(float(self.value())))

    def value(self):
        try:
            v = float(self.text().strip().replace(",", "."))
        except ValueError:
            return 0
        v = min(max(v, self.lo), self.hi)
        return round(v, self.dec) if self.dec else int(v)

    def setValue(self, v):
        if not v:
            self.setText("")
        elif self.dec:
            self.setText(f"{float(v):.{self.dec}f}".rstrip("0").rstrip("."))
        else:
            self.setText(str(int(v)))


def labeled(text, widget):
    box = QVBoxLayout()
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(6)
    lbl = QLabel(text)
    lbl.setObjectName("fieldLabel")
    box.addWidget(lbl)
    box.addWidget(widget)
    return box


def style_menu(m):
    """Menu with rounded corners, without the black frame Windows draws."""
    m.setWindowFlags(m.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
    m.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def metacritic_search_url(name):
    return "https://www.metacritic.com/search/" + urllib.parse.quote(name) + "/?category=13"


def hltb_url(name, hltb_id=None):
    if hltb_id:
        return f"https://howlongtobeat.com/game/{hltb_id}"
    return "https://howlongtobeat.com/?q=" + urllib.parse.quote(name)


def meta_other_text(g):
    """Warning for a Metacritic score that is not from the game's platform (Metacritic had none for it)."""
    mp = g.get("meta_platform")
    if mp and mp != g.get("platform"):
        return tr("⚠ This Metacritic score is from {used}, not from {platform}: Metacritic has none for it.",
                  used=plat_short(mp), platform=plat_short(g.get("platform") or "") or "—")
    return tr("⚠ This is the general Metacritic score: Metacritic does not list it by platform for this game.")


# --------------------------------------------------------------------------
# Add / edit game dialog
# --------------------------------------------------------------------------
class GameDialog(QDialog):
    def __init__(self, parent, game, config, years=None, cur_year=None, existing=None):
        super().__init__(parent)
        self.config = config
        self.cur_year = cur_year or time.localtime().tm_year
        self.editing = game is not None
        self.game = dict(game) if game else new_game()
        self.existing = existing or []   # every game, to warn about duplicates in the same list
        self.years = sorted(set(years or []) | {self.cur_year} | ({self.game["year"]} if self.game.get("year") else set()))
        self._save_pending = False       # Save was pressed while a search was running: save when it ends
        self._meta_plat = self.game.get("meta_platform")
        self._meta_other = bool(self.game.get("meta_other"))
        self.setAcceptDrops(True)        # an image dropped on the dialog becomes the cover
        self.setWindowTitle(tr("Edit game") if self.editing else tr("Add game"))
        self.setMinimumWidth(760)
        self._pix = None
        self._cover_changed = False
        self._last_query = self.game["name"] if self.editing else ""
        self._busy = False
        self._closed = False
        self._pick = None          # suggestion picked from the list (carries the exact ids)
        self._suggestions = []
        self._sug_token = 0
        self._auto_meta = None     # last Metacritic score filled in automatically
        self._meta_manual = False  # True if the Metacritic score was typed by the user

        self.bridge = Bridge(self)
        self.bridge.suggestions.connect(self.on_suggestions)
        self.bridge.info.connect(self.on_info)
        self.bridge.cover.connect(self.on_dropped_cover)

        self._sug_timer = QTimer(self)
        self._sug_timer.setSingleShot(True)
        self._sug_timer.setInterval(250)
        self._sug_timer.timeout.connect(self.request_suggestions)

        root = QHBoxLayout(self)
        root.setContentsMargins(26, 26, 26, 22)
        root.setSpacing(26)

        # --- cover column ---
        left = QVBoxLayout()
        left.setSpacing(10)
        self.cover_lbl = QLabel()
        self.cover_lbl.setFixedSize(200, 300)
        self.cover_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_lbl.setObjectName("coverPreview")
        self.cover_lbl.setToolTip(tr("You can also drop an image here (a file or one dragged from the browser)"))
        left.addWidget(self.cover_lbl)
        b_file = make_btn(tr("Choose image…"))
        b_paste = make_btn(tr("Paste from clipboard"))
        b_file.clicked.connect(self.pick_file)
        b_paste.clicked.connect(self.paste_cover)
        left.addWidget(b_file)
        left.addWidget(b_paste)
        left.addStretch(1)
        root.addLayout(left)

        # --- data column ---
        right = QVBoxLayout()
        right.setSpacing(14)

        self.name = QLineEdit(self.game["name"])
        self.name.setPlaceholderText(tr("Type the name: I'll suggest titles in case you mistype…"))
        self._sug_model = QStringListModel([], self)
        self.completer = QCompleter(self._sug_model, self)
        # unfiltered: so 'similar' titles also show up when there is a typo
        self.completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setMaxVisibleItems(8)
        self.completer.popup().setObjectName("suggestPopup")
        self.completer.activated[str].connect(self.on_suggestion_chosen)
        self.name.setCompleter(self.completer)
        self.name.textEdited.connect(lambda _t: self._sug_timer.start())
        self.name.editingFinished.connect(lambda: QTimer.singleShot(200, self.auto_if_new_name))
        right.addLayout(labeled(tr("Game"), self.name))

        self.avail_lbl = QLabel("")
        self.avail_lbl.setObjectName("hint")
        self.avail_lbl.setWordWrap(True)
        self.avail_lbl.setVisible(False)
        right.addWidget(self.avail_lbl)

        self.platform = make_combo()
        self.fill_platforms(PLATFORMS, self.game.get("platform") or "")
        self.platform.setToolTip(tr("You can pick any platform, even one the game is not detected on. "
                                    "The Metacritic score is looked up for the chosen one; if Metacritic does "
                                    "not have it you get a warning and the score of another platform"))
        self.platform.currentIndexChanged.connect(self.on_platform_changed)

        self.status = make_combo()
        for s in STATUSES:
            self.status.addItem(status_label(s), s)
        self.status.setCurrentIndex(max(self.status.findData(self.game["status"]), 0))

        # list (year) the game belongs to: lets you move a game to another year's list
        self.year_box = make_combo()
        for y in self.years:
            self.year_box.addItem(tr("List {year}", year=y), y)
        self.year_box.setCurrentIndex(max(self.year_box.findData(self.game.get("year") or self.cur_year), 0))

        row = QHBoxLayout()
        row.setSpacing(14)
        row.addLayout(labeled(tr("Platform"), self.platform), 3)
        row.addLayout(labeled(tr("Status"), self.status), 2)
        row.addLayout(labeled(tr("List"), self.year_box), 2)
        right.addLayout(row)

        self.platinum = QCheckBox(tr("🏆  Platinum earned"))
        self.platinum.setCursor(Qt.CursorShape.PointingHandCursor)
        self.platinum.setChecked(bool(self.game.get("platinum")))
        self.rerun = QCheckBox(tr("🔁  Rerun (replaying)"))
        self.rerun.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rerun.setToolTip(tr("Tick this if you are replaying this game: a RERUN tag will show on its card"))
        self.rerun.setChecked(bool(self.game.get("rerun")))
        checks = QHBoxLayout()
        checks.setSpacing(24)
        checks.addWidget(self.platinum)
        checks.addWidget(self.rerun)
        checks.addStretch(1)
        right.addLayout(checks)

        self.my = NumField(0, 10, 1, tr("No score"))
        self.my.setValue(float(self.game["my_score"] or 0))
        self.meta = NumField(0, 100, 0, "—")
        self.meta.setValue(int(self.game["meta_score"] or 0))
        self.meta.textEdited.connect(self._on_meta_typed)
        self.user = NumField(0, 10, 1, "—")
        self.user.setValue(float(self.game.get("user_score") or 0))
        self.hours = NumField(0, 5000, 1, "—")
        self.hours.setValue(float(self.game["hours"] or 0))
        self.h_main = NumField(0, 5000, 1, "—")
        self.h_main.setValue(float(self.game.get("hours_main") or 0))
        self.h_extra = NumField(0, 5000, 1, "—")
        self.h_extra.setValue(float(self.game.get("hours_extra") or 0))
        self.h_full = NumField(0, 5000, 1, "—")
        self.h_full.setValue(float(self.game.get("hours_100") or 0))

        if self._meta_other and self.game.get("meta_score"):
            self.meta.setToolTip(meta_other_text(self.game))

        # scores on one row, hours on the next (before, the user score was alone on a half-empty row)
        nums = QHBoxLayout()
        nums.setSpacing(14)
        nums.addLayout(labeled(tr("My score (0–10)"), self.my), 1)
        nums.addLayout(labeled(tr("Metacritic score"), self.meta), 1)
        nums.addLayout(labeled(tr("Metacritic user score (0–10)"), self.user), 1)
        right.addLayout(nums)

        times = QHBoxLayout()
        times.setSpacing(14)
        times.addLayout(labeled(tr("Index hours (HLTB)"), self.hours), 1)
        times.addLayout(labeled(tr("Story (h)"), self.h_main), 1)
        times.addLayout(labeled(tr("Story + extras (h)"), self.h_extra), 1)
        times.addLayout(labeled(tr("Completionist (h)"), self.h_full), 1)
        right.addLayout(times)

        self.notes = QLineEdit(self.game["notes"])
        self.notes.setPlaceholderText(tr("Comments…"))
        right.addLayout(labeled(tr("Notes"), self.notes))

        self.index_lbl = QLabel()
        self.index_lbl.setObjectName("indexPreview")
        right.addWidget(self.index_lbl)
        for w in (self.user, self.hours):
            w.valueChanged.connect(self.update_index)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.auto_btn = make_btn(tr("✨  Autofill"), "soft",
                                 tr("Looks up cover art, Metacritic score (for the chosen platform) and "
                                    "HowLongToBeat hours (overwrites what is there)"))
        self.auto_btn.clicked.connect(lambda _=False: self.run_auto(overwrite=True))
        actions.addWidget(self.auto_btn)
        mc_btn = make_btn(tr("Open Metacritic"), "ghost",
                          tr("Opens the Metacritic search so you can check the score or enter it by hand"))
        mc_btn.clicked.connect(self.open_metacritic)
        actions.addWidget(mc_btn)
        hl_btn = make_btn(tr("Open HowLongToBeat"), "ghost",
                          tr("Opens the game page on HowLongToBeat so you can check the hours or enter them by hand"))
        hl_btn.clicked.connect(self.open_hltb)
        actions.addWidget(hl_btn)
        actions.addStretch(1)
        right.addLayout(actions)

        self.status_lbl = QLabel("")
        self.status_lbl.setObjectName("hint")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setMinimumHeight(34)
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        right.addWidget(self.status_lbl)
        right.addStretch(1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        save_b = bb.button(QDialogButtonBox.StandardButton.Save)
        cancel_b = bb.button(QDialogButtonBox.StandardButton.Cancel)
        self.save_b = save_b
        save_b.setText(tr("Save"))
        save_b.setObjectName("primary")
        cancel_b.setText(tr("Cancel"))
        cancel_b.setObjectName("ghost")
        for b in (save_b, cancel_b):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        bb.accepted.connect(self.try_accept)
        bb.rejected.connect(self.reject)
        right.addWidget(bb)
        root.addLayout(right, 1)

        if self.game["cover"]:
            pm = QPixmap(str(COVERS_DIR / self.game["cover"]))
            if not pm.isNull():
                self._pix = pm
        self.show_cover()
        self.update_index()

    # ---- cover ----
    def show_cover(self):
        if self._pix is None:
            self.cover_lbl.setText(tr("No cover") + "\n\n🎮")
            self.cover_lbl.setPixmap(QPixmap())
            return
        scaled = self._pix.scaled(self.cover_lbl.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
        self.cover_lbl.setPixmap(scaled)

    def set_cover_pixmap(self, pm):
        if pm is None or pm.isNull():
            return
        self._pix = pm
        self._cover_changed = True
        self.show_cover()

    def pick_file(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Choose cover"), "",
                                              tr("Images (*.png *.jpg *.jpeg *.webp *.bmp)"))
        if path:
            self.set_cover_pixmap(QPixmap(path))

    def paste_cover(self):
        img = QGuiApplication.clipboard().image()
        if img.isNull():
            self.status_lbl.setText(tr("There is no image on the clipboard."))
            return
        self.set_cover_pixmap(QPixmap.fromImage(img))

    # ---- image dropped on the dialog: file, image data or a link to an image ----
    def _drop_source(self, md):
        if md.hasImage():
            return "image"
        for u in md.urls():
            if u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in IMAGE_EXTS:
                return "file"
            if u.scheme() in ("http", "https"):
                return "url"
        return None

    def dragEnterEvent(self, e):
        if self._drop_source(e.mimeData()):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if self._drop_source(e.mimeData()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        kind = self._drop_source(md)
        if not kind:
            return
        e.acceptProposedAction()
        if kind == "image":
            img = md.imageData()
            pm = QPixmap.fromImage(img) if img is not None else QPixmap()
            self.set_cover_pixmap(pm)
        elif kind == "file":
            path = next(u.toLocalFile() for u in md.urls()
                        if u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in IMAGE_EXTS)
            self.set_cover_pixmap(QPixmap(path))
        else:
            url = next(u.toString() for u in md.urls() if u.scheme() in ("http", "https"))
            self.status_lbl.setText(tr("Downloading the image…"))
            self.status_lbl.setStyleSheet("")

            def job():
                try:
                    data = http_get(url)
                except Exception:
                    data = None
                try:
                    self.bridge.cover.emit(data)
                except RuntimeError:
                    pass   # the dialog has already been closed

            threading.Thread(target=job, daemon=True).start()

    def on_dropped_cover(self, data):
        if self._closed:
            return
        pm = QPixmap()
        if data and pm.loadFromData(data):
            self.set_cover_pixmap(pm)
            self.status_lbl.setText("✅ " + tr("cover"))
        else:
            self.status_lbl.setText(tr("That link is not an image I can use: save it and choose it with “Choose image…”."))

    def open_metacritic(self):
        text = self.name.text().strip()
        if text:
            QDesktopServices.openUrl(QUrl(metacritic_search_url(text)))

    def current_hltb_id(self):
        """HowLongToBeat id of the typed game: the one from the chosen suggestion or the one already saved."""
        text = self.name.text().strip()
        if self._pick and _norm(self._pick.get("name")) == _norm(text) and self._pick.get("hltb_id"):
            return self._pick["hltb_id"]
        if self.game.get("hltb_id") and _norm(self.game.get("name")) == _norm(text):
            return self.game["hltb_id"]
        return None

    def open_hltb(self):
        text = self.name.text().strip()
        if not text:
            return
        QDesktopServices.openUrl(QUrl(hltb_url(text, self.current_hltb_id())))

    # ---- live index ----
    def current_values(self):
        return {
            "user_score": self.user.value() or None,
            "hours": self.hours.value() or None,
        }

    def update_index(self, *_):
        idx = index_of(self.current_values())
        if idx is None:
            self.index_lbl.setText(tr("Index: — (needs the Metacritic user score and hours)"))
        else:
            self.index_lbl.setText(tr("Index: {v}", v=f"{idx:.1f}"))

    # ---- available platforms ----
    def fill_platforms(self, plats, selected=""):
        items = list(plats)
        if selected and selected not in items:
            items.append(selected)  # never lose the platform that is already saved
        self.platform.blockSignals(True)
        self.platform.clear()
        self.platform.addItem(tr("— Not specified —"), "")
        for pl in items:
            self.platform.addItem(plat_label(pl), pl)
        self.platform.setCurrentIndex(max(self.platform.findData(selected), 0))
        self.platform.blockSignals(False)

    def set_available_platforms(self, plats):
        """Say which platforms the game is on according to the websites. The dropdown keeps ALL of them: if
        detection fails (or it does not list PS5 and the game does run on PS5) you can pick any platform."""
        if not plats:
            return
        self.avail_lbl.setText(tr("Available on: ") + ", ".join(plats) + tr(" (you can still pick any other platform)"))
        self.avail_lbl.setVisible(True)

    # ---- name suggestions ----
    def request_suggestions(self):
        text = self.name.text().strip()
        if len(text) < 3 or self._closed:
            return
        self._sug_token += 1
        token = self._sug_token
        is_current = lambda: token == self._sug_token and not self._closed
        threading.Thread(target=suggest_job, args=(token, text, is_current, self._emit_suggestions),
                         daemon=True).start()

    def _emit_suggestions(self, token, items, final):
        try:
            self.bridge.suggestions.emit(token, items, final)
        except RuntimeError:
            pass  # the dialog has already been closed

    def on_suggestions(self, token, items, final):
        if self._closed or token != self._sug_token:
            return  # old response: the user kept typing
        self._suggestions = items
        self._sug_model.setStringList([s["name"] for s in items])
        if items and self.name.hasFocus():
            self.completer.complete()

    def on_suggestion_chosen(self, text):
        self._sug_token += 1          # discard suggestions that are still on their way
        self._sug_timer.stop()
        self.name.setText(text)
        self._pick = next((s for s in self._suggestions if s["name"] == text), None)
        self._last_query = text
        if self._pick:
            self.set_available_platforms(map_platforms(self._pick.get("platforms")))
        self.run_auto(overwrite=True)

    # ---- platform ----
    def _on_meta_typed(self, *_):
        self._meta_manual = True
        self._meta_plat, self._meta_other = None, False   # typed by hand: no warning to keep
        self.meta.setToolTip("")

    def on_platform_changed(self, *_):
        """When the platform changes, the Metacritic score becomes the new platform's (unless you typed it yourself)."""
        text = self.name.text().strip()
        if not text or self._busy:
            return
        if self._meta_manual and self.meta.value():
            self.status_lbl.setText(tr("Press ✨ Autofill to look up the score for this platform."))
            self.status_lbl.setStyleSheet("")
        else:
            self.run_auto(overwrite=False, meta_only=True)

    def _select_platform(self, name):
        self.platform.blockSignals(True)
        i = self.platform.findData(name)
        if i < 0:
            self.platform.addItem(plat_label(name), name)
            i = self.platform.count() - 1
        self.platform.setCurrentIndex(i)
        self.platform.blockSignals(False)

    # ---- autofill ----
    def auto_if_new_name(self):
        text = self.name.text().strip()
        if text and text != self._last_query and not self._closed:
            self.run_auto(overwrite=False)

    def run_auto(self, overwrite, meta_only=False):
        text = self.name.text().strip()
        if not text or self._busy:
            return
        self._busy = True
        if not meta_only:
            self._last_query = text
        pick = self._pick if (self._pick and _norm(self._pick["name"]) == _norm(text)) else None
        self.auto_btn.setEnabled(False)
        self.status_lbl.setText(tr("🔎 Searching…"))
        self.status_lbl.setStyleSheet("")
        args = (text, self.platform.currentData() or "", pick, meta_only)

        def job():
            try:
                info = fetch_game_info(*args)
            except Exception as e:  # never break the app because of the network
                info = {"name": None, "cover": None, "meta": None, "meta_platform": None,
                        "hours": None, "platforms": [], "log": [f"Error: {e}"]}
            try:
                self.bridge.info.emit(info, overwrite, meta_only)
            except RuntimeError:
                pass  # the dialog has already been closed

        threading.Thread(target=job, daemon=True).start()

    def on_info(self, info, overwrite, meta_only=False):
        if self._closed:
            return
        self._busy = False
        self.auto_btn.setEnabled(True)
        got = []

        # name corrected if it was an obvious typo
        typed = self.name.text().strip()
        canon = info.get("name")
        if not meta_only and canon and canon != typed and _sim(typed, canon) >= 0.8:
            self.name.setText(canon)
            self._last_query = canon
            got.append(tr("name corrected to “{name}”", name=canon))

        if not meta_only and info.get("cover") and (overwrite or self._pix is None):
            pm = QPixmap()
            if pm.loadFromData(info["cover"]):
                self.set_cover_pixmap(pm)
                got.append(tr("cover"))

        # default platform (only if none was chosen)
        if info.get("platforms"):
            self.set_available_platforms(info["platforms"])
        if not meta_only and info.get("platform") and not self.platform.currentData():
            self._select_platform(info["platform"])
            got.append(tr("platform ({p})", p=PLATFORM_SHORT.get(info['platform'], info['platform'])))

        # Metacritic score (of the chosen platform)
        auto_meta = (not self._meta_manual) or self.meta.value() == 0
        if info.get("meta"):
            if overwrite or auto_meta:
                self.meta.setValue(int(info["meta"]))
                self._auto_meta = int(info["meta"])
                self._meta_manual = False
                self._meta_other = bool(info.get("meta_notice"))
                self._meta_plat = info.get("meta_platform") if self._meta_other else None
                if self._meta_other and self._meta_plat == (self.platform.currentData() or None):
                    self._meta_plat = None   # general score (not by platform): no platform to name
                label = info.get("meta_platform") or self.platform.currentData() or "general"
                got.append(f"Metacritic ({PLATFORM_SHORT.get(label, label)})")
        elif meta_only and auto_meta and self.meta.value():
            self.meta.setValue(0)  # the previous score belonged to another platform
            self._auto_meta = None
            self._meta_plat, self._meta_other = None, False

        # Metacritic user score (0-10)
        if info.get("user") and (overwrite or not self.user.value()):
            self.user.setValue(float(info["user"]))
            got.append(tr("user score"))

        # hours: the index hours (HLTB default) and the three durations (missing ones stay empty)
        if not meta_only:
            if info.get("hours") and (overwrite or not self.hours.value()):
                self.hours.setValue(float(info["hours"]))
                got.append(tr("hours"))
            if info.get("hltb_found"):
                for fld, key in ((self.h_main, "hours_main"), (self.h_extra, "hours_extra"),
                                 (self.h_full, "hours_100")):
                    if overwrite or not fld.value():
                        fld.setValue(info.get(key) or 0)

        parts = []
        if got:
            parts.append("✅ " + ", ".join(got))
        if info.get("log"):
            parts.append("; ".join(info["log"]))
        self.status_lbl.setText("\n".join(parts) if parts else tr("Nothing found, fill it in by hand."))
        notice = info.get("meta_notice")   # score from another platform: the warning is shown in amber and on the field itself
        self.status_lbl.setStyleSheet(f"color: {TH['WARN']};" if notice else "")
        if info.get("meta") or meta_only:
            self.meta.setToolTip(notice or "")
        if self._save_pending:   # Save was pressed during the search: save now, with the data that arrived
            self._save_pending = False
            self.save_b.setEnabled(True)
            QTimer.singleShot(0, self.try_accept)

    # ---- saving ----
    def try_accept(self):
        text = self.name.text().strip()
        if not text:
            self.status_lbl.setText(tr("Give the game a name."))
            return
        if not self._busy and not self.editing and text != self._last_query:
            # a new game whose name was never looked up (for example Enter right after typing it): look it up first
            self.run_auto(overwrite=False)
        if self._busy:
            # saving now would throw away what the search is about to fill in: wait for it
            self._save_pending = True
            self.save_b.setEnabled(False)
            self.status_lbl.setText(tr("🔎 Searching… the game will be saved as soon as the search finishes."))
            self.status_lbl.setStyleSheet("")
            return
        if not self.confirm_not_duplicate(text):
            return
        self._closed = True
        self.accept()

    def confirm_not_duplicate(self, text):
        """Warn if another game with the same name is already in the chosen list."""
        year = self.year_box.currentData()
        key = _fold(text)
        if not any(g.get("id") != self.game["id"] and g.get("year") == year and _fold(g.get("name")) == key
                   for g in self.existing):
            return True
        return confirm_box(self, tr("Game already in the list"),
                           tr("“{name}” is already in the {year} list. Save it anyway?", name=text, year=year),
                           tr("Save anyway"))

    def reject(self):
        self._closed = True
        super().reject()

    def result_game(self):
        g = self.game
        g["hltb_id"] = self.current_hltb_id()   # read the saved hltb_id before the name is overwritten
        g["name"] = self.name.text().strip()
        g["status"] = self.status.currentData() or "Planeado"
        g["platform"] = self.platform.currentData() or ""
        g["platinum"] = self.platinum.isChecked()
        g["rerun"] = self.rerun.isChecked()
        g["my_score"] = self.my.value() or None
        g["meta_score"] = self.meta.value() or None
        g["meta_other"] = bool(self._meta_other and g["meta_score"])
        g["meta_platform"] = self._meta_plat if g["meta_other"] else None
        g["user_score"] = self.user.value() or None
        g["hours"] = self.hours.value() or None
        g["hours_main"] = self.h_main.value() or None
        g["hours_extra"] = self.h_extra.value() or None
        g["hours_100"] = self.h_full.value() or None
        g["year"] = self.year_box.currentData() or g.get("year") or self.cur_year
        g["notes"] = self.notes.text().strip()
        if self._cover_changed and self._pix is not None:
            ensure_dirs()
            old = g.get("cover")
            fname = f"{g['id']}_{int(time.time())}.jpg"
            pm = self._pix
            if pm.width() > 600 or pm.height() > 900:
                pm = pm.scaled(600, 900, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            pm.save(str(COVERS_DIR / fname), "JPG", 90)
            g["cover"] = fname
            if old:
                try:
                    (COVERS_DIR / old).unlink()
                except OSError:
                    pass
        return g


# --------------------------------------------------------------------------
# Game card (delegate)
# --------------------------------------------------------------------------
CARD_W, CARD_H = 210, 470
COVER_W, COVER_H = 174, 261


def score_color(v, top):
    """Green from 7.5 (75 on Metacritic), yellow otherwise, red below 5 (50)."""
    if v is None:
        return TH["SCORE_NONE"]
    r = v / top
    if r >= 0.75:
        return TH["SCORE_HI"]
    if r >= 0.5:
        return TH["SCORE_MID"]
    return TH["SCORE_LO"]


def meta_color(v):
    return score_color(v, 100)


def fit_label(p, key, short, width):
    """Translated label if it fits in 'width' with the painter's current font; otherwise the short version."""
    full = tr(key)
    return full if p.fontMetrics().horizontalAdvance(full) <= width - 4 else short


def draw_platinum(p, rect):
    """Round platinum badge with a trophy drawn as vectors."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    rf = QRectF(rect)
    grad = QLinearGradient(rf.topLeft(), rf.bottomRight())
    grad.setColorAt(0.0, QColor("#f7fbff"))
    grad.setColorAt(0.5, QColor("#c3cfe6"))
    grad.setColorAt(1.0, QColor("#8fa0c4"))
    p.setPen(QPen(QColor("#ffffff"), 1.5))
    p.setBrush(grad)
    p.drawEllipse(rf)
    s = rect.width() / 32.0
    p.translate(rect.x(), rect.y())
    p.scale(s, s)
    dark = QColor("#2b3354")
    cup = QPainterPath()
    cup.moveTo(10, 8)
    cup.lineTo(22, 8)
    cup.lineTo(21, 15)
    cup.quadTo(20.5, 19.5, 16, 20)
    cup.quadTo(11.5, 19.5, 11, 15)
    cup.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(dark)
    p.drawPath(cup)
    p.drawRect(QRectF(15, 19.5, 2, 4))
    p.drawRoundedRect(QRectF(11, 23, 10, 2.4), 1.2, 1.2)
    pen = QPen(dark, 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    h1 = QPainterPath()
    h1.moveTo(10, 10)
    h1.cubicTo(5.5, 10, 6, 16, 11, 16.5)
    h2 = QPainterPath()
    h2.moveTo(22, 10)
    h2.cubicTo(26.5, 10, 26, 16, 21, 16.5)
    p.drawPath(h1)
    p.drawPath(h2)
    p.restore()


class CardDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache = {}
        self.games = {}   # id -> game (filled in by the window on every refresh)
        self.zoom = 1.0       # only informative: card width / CARD_W
        self.cell_w = None    # width of each grid cell
        self.card_px = None   # width the card is drawn at (the cell width, up to a limit)

    def card_w(self):
        return self.card_px or CARD_W

    def card_h(self, w=None):
        """Card height for a card width: only the cover grows or shrinks (keeping its 2:3 shape); the text
        below it always has the same size, so it is drawn at its real size and stays sharp."""
        cover_w = (w or self.card_w()) - 36   # 8 + 8 card margin and 10 + 10 cover margin
        return CARD_H + round(cover_w * COVER_H / COVER_W) - COVER_H

    def sizeHint(self, option, index):
        return QSize(self.cell_w or self.card_w(), self.card_h() + 2)

    def cover_pix(self, filename):
        if not filename:
            return None
        if filename in self._cache:
            return self._cache[filename]
        pm = QPixmap(str(COVERS_DIR / filename))
        if pm.isNull():
            self._cache[filename] = None
            return None
        W, H = COVER_W * 2, COVER_H * 2   # double size: stays sharp when the card is drawn bigger
        scaled = pm.scaled(W, H, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
        out = scaled.copy((scaled.width() - W) // 2, (scaled.height() - H) // 2, W, H)
        self._cache[filename] = out
        return out

    def paint(self, p, option, index):
        g = self.games.get(index.data(ROLE_ID))
        if not g:
            return
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # drawn at its real width (never scaled: scaled text looks blurry), centered in its cell
        W = self.card_w()
        dx = max(0, (option.rect.width() - W) // 2)
        p.translate(option.rect.x() + dx, option.rect.y())
        r = QRect(0, 0, W, self.card_h()).adjusted(8, 8, -8, -8)
        color = QColor(STATUS_COLORS.get(g["status"], "#8b93ad"))
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        path = QPainterPath()
        path.addRoundedRect(QRectF(r), 16, 16)
        p.fillPath(path, QColor(CARD))
        tint = QColor(color)
        tint.setAlpha(round((46 if g["status"] != "Planeado" else 18) * TH["CARD_TINT"]))
        p.fillPath(path, tint)
        if selected:   # selected (one or several with Ctrl / Shift): purple border and a light purple veil
            veil = QColor(ACCENT)
            veil.setAlpha(40)
            p.fillPath(path, veil)
            p.setPen(QPen(QColor(ACCENT_HI), 4))
        else:
            pen_col = QColor(color)
            if not hovered:
                pen_col.setAlpha(TH["CARD_EDGE"][0])
            p.setPen(QPen(pen_col, TH["CARD_EDGE"][2] if hovered else TH["CARD_EDGE"][1]))
        p.drawPath(path)

        # cover
        cover_h = round((r.width() - 20) * COVER_H / COVER_W)
        cr = QRect(r.x() + 10, r.y() + 10, r.width() - 20, cover_h)
        oy = r.y() + cover_h - COVER_H   # everything under the cover moves down / up with its height
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(cr), 11, 11)
        p.setClipPath(clip)
        pm = self.cover_pix(g.get("cover"))
        if pm:
            p.drawPixmap(QRectF(cr), pm, QRectF(pm.rect()))
        else:
            p.fillRect(cr, QColor(TH["COVER_EMPTY"]))
            f = QFont(p.font())
            f.setPointSize(30)
            p.setFont(f)
            p.setPen(QColor(TH["COVER_EMPTY_ICON"]))
            p.drawText(cr, A_CENTER, "🎮")
        p.setClipping(False)

        # status pill
        f = QFont(p.font())
        f.setPointSize(8)
        f.setBold(True)
        p.setFont(f)
        fm = QFontMetrics(f)
        label = status_label(g["status"])
        pw = fm.horizontalAdvance(label) + 20
        pill = QRect(cr.x() + 8, cr.y() + 8, pw, 22)
        pp = QPainterPath()
        pp.addRoundedRect(QRectF(pill), 11, 11)
        p.fillPath(pp, color)
        p.setPen(QColor("#10121b"))
        p.drawText(pill, A_CENTER, label)

        # platform (bottom right of the cover, neutral so it does not clash with the status colors)
        plat = g.get("platform") or ""
        if plat:
            ptxt = plat_short(plat)
            pw2 = fm.horizontalAdvance(ptxt) + 18
            prect = QRect(cr.right() - pw2 - 5, cr.bottom() - 27, pw2, 22)
            pp2 = QPainterPath()
            pp2.addRoundedRect(QRectF(prect), 11, 11)
            p.fillPath(pp2, QColor(12, 14, 24, 215))
            p.setPen(QColor("#e6e8f2"))
            p.drawText(prect, A_CENTER, ptxt)

        # platinum trophy (bottom left of the cover)
        if g.get("platinum"):
            draw_platinum(p, QRect(cr.x() + 6, cr.bottom() - 35, 30, 30))

        # RERUN tag (top right of the cover)
        if g.get("rerun"):
            rw = fm.horizontalAdvance("RERUN") + 18
            rrect = QRect(cr.right() - rw - 6, cr.y() + 8, rw, 22)
            rp = QPainterPath()
            rp.addRoundedRect(QRectF(rrect), 11, 11)
            p.fillPath(rp, QColor(ACCENT))
            p.setPen(QColor("#ffffff"))
            p.drawText(rrect, A_CENTER, "RERUN")

        # title
        f = QFont(p.font())
        f.setPointSize(11)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(TH["CARD_TITLE"]))
        trect = QRect(r.x() + 12, oy + 279, r.width() - 24, 22)
        title = QFontMetrics(f).elidedText(g["name"], Qt.TextElideMode.ElideRight, trect.width())
        p.drawText(trect, A_LEFT, title)

        # three figures: Metacritic user score / You / Hours
        col_w = (r.width() - 20) // 3
        vals = [
            (None, f"{g['user_score']:g}" if g.get("user_score") is not None else "—",
             score_color(g.get("user_score"), 10)),   # the label is chosen when drawing (see below)
            (tr("You"), f"{g['my_score']:g}" if g.get("my_score") is not None else "—",
             score_color(g.get("my_score"), 10)),
            (tr("Hours"), f"{g['hours']:g} h" if g.get("hours") else "—", TH["CARD_VALUE"]),
        ]
        for i, (lab, val, col) in enumerate(vals):
            x = r.x() + 10 + i * col_w
            f1 = QFont(p.font())
            f1.setPointSize(8)
            f1.setBold(False)
            p.setFont(f1)
            p.setPen(QColor(TH["CARD_LABEL"]))
            if lab is None:   # Metacritic user score: 'Meta Users' if it fits, otherwise 'Meta U.'
                lab = fit_label(p, "Meta Users", "Meta U.", col_w)
            p.drawText(QRect(x, oy + 306, col_w, 14), A_CENTER, lab)
            f2 = QFont(p.font())
            f2.setPointSize(12)
            f2.setBold(True)
            p.setFont(f2)
            p.setPen(QColor(col))
            p.drawText(QRect(x, oy + 320, col_w, 24), A_CENTER, val)

        # two bars: critic score (the page's Metascore) and index
        idx = index_of(g)
        other = bool(g.get("meta_other") and g.get("meta_score") is not None)
        meta_lab = "Metascore"
        if other:   # the score is from another platform (or the general one): say so on the card
            mp = g.get("meta_platform")
            meta_lab = f"Metascore ⚠ {plat_short(mp)}" if mp else "Metascore ⚠"
        for y_off, lab, val, col in (
                (350, meta_lab, str(g["meta_score"]) if g.get("meta_score") is not None else "—",
                 meta_color(g.get("meta_score"))),
                (380, tr("Index"), f"{idx:.1f}" if idx is not None else "—",
                 TH["INDEX"] if idx is not None else TH["NONE"])):
            bar = QRect(r.x() + 10, oy + y_off, r.width() - 20, 26)
            bp = QPainterPath()
            bp.addRoundedRect(QRectF(bar), 8, 8)
            p.fillPath(bp, QColor(TH["BAR"]))
            f = QFont(p.font())
            f.setPointSize(9)
            f.setBold(True)
            p.setFont(f)
            warn = other and y_off == 350
            if warn and p.fontMetrics().horizontalAdvance(lab) > bar.width() - 60:
                lab = "Metascore ⚠"   # no room for the platform next to the score
            p.setPen(QColor(TH["WARN"] if warn else TH["BAR_LABEL"]))
            p.drawText(bar.adjusted(10, 0, 0, 0), A_LEFT, lab)
            f.setPointSize(12)
            p.setFont(f)
            p.setPen(QColor(col))
            p.drawText(bar.adjusted(0, 0, -10, 0), A_RIGHT, val)

        # HowLongToBeat durations: only the ones that exist (a game with no extras shows no '+Extras')
        chips = [(tr(lab), g.get(key)) for lab, key in (("Story", "hours_main"), ("+Extras", "hours_extra"),
                                                    ("Complete", "hours_100")) if g.get(key)]
        if chips:
            # equal columns, with the same centers as the row above (Meta U. / You / Hours), so the numbers line up.
            # The label is drawn centered on its column without being clipped: "Completista" is a little wider
            # than its column, but there is room for it (before, it was cut off).
            cw = (r.width() - 20) // len(chips)
            f1 = QFont(p.font())
            f1.setBold(False)
            f1.setPointSize(8)
            fm1 = QFontMetrics(f1)
            lws = [fm1.horizontalAdvance(lab) for lab, _ in chips]
            # one point smaller only if a label would not fit even with that extra room, or if two
            # neighbouring labels would end up less than 6 px apart (narrow cards)
            if (max(lws) > cw + 22
                    or any(cw - (lws[k] + lws[k + 1]) / 2 < 6 for k in range(len(lws) - 1))):
                f1.setPointSize(7)
            f2 = QFont(p.font())
            f2.setPointSize(10)
            f2.setBold(True)
            for i, (lab, v) in enumerate(chips):
                cx = r.x() + 10 + i * cw + cw / 2        # center of the column
                lw = cw + 22                             # the label may spill a little over its neighbors' margin
                p.setFont(f1)
                p.setPen(QColor(TH["CARD_SUB"]))
                p.drawText(QRectF(cx - lw / 2, oy + 412, lw, 15), A_CENTER, lab)
                p.setFont(f2)
                p.setPen(QColor(TH["CARD_VALUE"]))
                p.drawText(QRectF(cx - cw / 2, oy + 427, cw, 18), A_CENTER, f"{v:g} h")
        p.restore()


ROW_H = 98
THUMB_W, THUMB_H = 50, 75


class RowDelegate(QStyledItemDelegate):
    """List / details view: one row per game with thumbnail, status, platform and data."""
    COLS = ("Meta", "Users", "You", "Hours", "Index")
    COL_W = 76

    def __init__(self, view):
        super().__init__(view)
        self.lv = view
        self._cache = {}
        self.games = {}   # id -> game (filled in by the window on every refresh)
        self.zoom = 1.0

    def sizeHint(self, option, index):
        return QSize(max(300, self.lv.viewport().width()), round(ROW_H * self.zoom))

    def thumb(self, filename):
        if not filename:
            return None
        if filename in self._cache:
            return self._cache[filename]
        pm = QPixmap(str(COVERS_DIR / filename))
        if pm.isNull():
            self._cache[filename] = None
            return None
        BW, BH = THUMB_W * 2, THUMB_H * 2   # doubled so it looks sharp
        sc = pm.scaled(BW, BH, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                       Qt.TransformationMode.SmoothTransformation)
        out = sc.copy((sc.width() - BW) // 2, (sc.height() - BH) // 2, BW, BH)
        self._cache[filename] = out
        return out

    def paint(self, p, option, index):
        g = self.games.get(index.data(ROLE_ID))
        if not g:
            return
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # drawn at the normal size (height ROW_H) and the zoom scales the painter; the logical width is adjusted
        p.translate(float(option.rect.x()), float(option.rect.y()))
        p.scale(self.zoom, self.zoom)
        r = QRect(0, 0, round(option.rect.width() / self.zoom), ROW_H).adjusted(2, 4, -2, -4)
        color = QColor(STATUS_COLORS.get(g["status"], "#8b93ad"))
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        path = QPainterPath()
        path.addRoundedRect(QRectF(r), 14, 14)
        p.fillPath(path, QColor(CARD))
        tint = QColor(color)
        tint.setAlpha(round((46 if g["status"] != "Planeado" else 18) * TH["CARD_TINT"]))
        p.fillPath(path, tint)
        if selected:   # selected (one or several with Ctrl / Shift): purple border and a light purple veil
            veil = QColor(ACCENT)
            veil.setAlpha(40)
            p.fillPath(path, veil)
            p.setPen(QPen(QColor(ACCENT_HI), 4))
        else:
            pen_col = QColor(color)
            if not hovered:
                pen_col.setAlpha(TH["CARD_EDGE"][0])
            p.setPen(QPen(pen_col, TH["CARD_EDGE"][2] if hovered else TH["CARD_EDGE"][1]))
        p.drawPath(path)

        # thumbnail
        trect = QRect(r.x() + 10, r.y() + (r.height() - THUMB_H) // 2, THUMB_W, THUMB_H)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(trect), 8, 8)
        p.setClipPath(clip)
        pm = self.thumb(g.get("cover"))
        if pm:
            p.drawPixmap(trect, pm)
        else:
            p.fillRect(trect, QColor(TH["COVER_EMPTY"]))
            f = QFont(p.font())
            f.setPointSize(16)
            p.setFont(f)
            p.setPen(QColor(TH["COVER_EMPTY_ICON"]))
            p.drawText(trect, A_CENTER, "🎮")
        p.setClipping(False)

        # data columns on the right (if there is not enough room, the leftmost ones are dropped)
        x0 = trect.right() + 16
        n = len(self.COLS)
        while n > 0 and (r.right() - 10 - n * self.COL_W) - x0 - 10 < 220:
            n -= 1
        cx = r.right() - 10 - n * self.COL_W
        text_w = max(60, cx - x0 - 10)
        idx = index_of(g)
        values = {
            "Meta": (str(g["meta_score"]) if g.get("meta_score") is not None else "—", meta_color(g.get("meta_score"))),
            "Users": (f"{g['user_score']:g}" if g.get("user_score") is not None else "—",
                      score_color(g.get("user_score"), 10)),
            "You": (f"{g['my_score']:g}" if g.get("my_score") is not None else "—", score_color(g.get("my_score"), 10)),
            "Hours": (f"{g['hours']:g} h" if g.get("hours") else "—", TH["CARD_VALUE"]),
            "Index": (f"{idx:.1f}" if idx is not None else "—", TH["INDEX"] if idx is not None else TH["NONE"]),
        }
        mid = r.center().y()
        if n:
            p.setPen(QColor(*TH["DIVIDER"]))
            p.drawLine(cx - 6, r.y() + 14, cx - 6, r.bottom() - 14)
        for i, lab in enumerate(self.COLS[len(self.COLS) - n:]):
            x = cx + i * self.COL_W
            f1 = QFont(p.font())
            f1.setPointSize(8)
            f1.setBold(False)
            p.setFont(f1)
            p.setPen(QColor(TH["CARD_LABEL"]))
            head = fit_label(p, "Meta Users", "Meta U.", self.COL_W) if lab == "Users" else tr(lab)
            p.drawText(QRect(x, mid - 24, self.COL_W, 14), A_CENTER, head)
            f2 = QFont(p.font())
            f2.setPointSize(12)
            f2.setBold(True)
            p.setFont(f2)
            val, col = values[lab]
            p.setPen(QColor(col))
            p.drawText(QRect(x, mid - 8, self.COL_W, 26), A_CENTER, val)

        # name
        p.setClipRect(QRect(x0, r.y(), text_w, r.height()))
        f = QFont(p.font())
        f.setPointSize(11)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(TH["CARD_TITLE"]))
        title = QFontMetrics(f).elidedText(g["name"], Qt.TextElideMode.ElideRight, text_w)
        p.drawText(QRect(x0, r.y() + 8, text_w, 24), A_LEFT, title)

        # status, platform and platinum
        f = QFont(p.font())
        f.setPointSize(8)
        f.setBold(True)
        p.setFont(f)
        fm = QFontMetrics(f)
        y2 = r.y() + 36
        pw = fm.horizontalAdvance(status_label(g["status"])) + 20
        pill = QRect(x0, y2, pw, 22)
        pp = QPainterPath()
        pp.addRoundedRect(QRectF(pill), 11, 11)
        p.fillPath(pp, color)
        p.setPen(QColor("#10121b"))
        p.drawText(pill, A_CENTER, status_label(g["status"]))
        cur = pill.right() + 8
        plat = g.get("platform") or ""
        if plat:
            ptxt = plat_short(plat)
            pw2 = fm.horizontalAdvance(ptxt) + 18
            prect = QRect(cur, y2, pw2, 22)
            pp2 = QPainterPath()
            pp2.addRoundedRect(QRectF(prect), 11, 11)
            p.fillPath(pp2, QColor(12, 14, 24, 215))
            p.setPen(QColor("#e6e8f2"))
            p.drawText(prect, A_CENTER, ptxt)
            cur = prect.right() + 8
        if g.get("platinum"):
            draw_platinum(p, QRect(cur, y2 - 2, 26, 26))
            cur += 34
        if g.get("rerun"):
            rw = fm.horizontalAdvance("RERUN") + 18
            rrect = QRect(cur, y2, rw, 22)
            rp = QPainterPath()
            rp.addRoundedRect(QRectF(rrect), 11, 11)
            p.fillPath(rp, QColor(ACCENT))
            p.setPen(QColor("#ffffff"))
            p.drawText(rrect, A_CENTER, "RERUN")

        # HowLongToBeat durations (only those that exist) or, if there are none, the notes
        parts = [f"{tr(lab)} {g[key]:g} h" for lab, key in (("Story", "hours_main"), ("+Extras", "hours_extra"),
                                                      ("Complete", "hours_100")) if g.get(key)]
        info = "   ·   ".join(parts) or (g.get("notes") or "")
        if info:
            f = QFont(p.font())
            f.setPointSize(8)
            f.setBold(False)
            p.setFont(f)
            p.setPen(QColor(TH["CARD_SUB"]))
            info = QFontMetrics(f).elidedText(info, Qt.TextElideMode.ElideRight, text_w)
            p.drawText(QRect(x0, r.y() + 62, text_w, 18), A_LEFT, info)
        p.restore()


# --------------------------------------------------------------------------
# Tier list (one per list / year)
# --------------------------------------------------------------------------
TIER_FILE = DATA_DIR / "tierlists.json"
TIER_PHOTOS = DATA_DIR / "tierlists"   # the tier list photo (PNG) of each year is stored here
TIER_MIME = "backlog-game:"
TIER_W, TIER_H, TIER_PAD = 78, 104, 6  # cover size at 100 % zoom
TIER_CTRL_W = 32                       # column of ▲ ⚙ ▼ buttons to the right of each row (not included in the photo)
ZOOMS = [0.5, 0.65, 0.8, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5]
DEFAULT_TIERS = [("S", "#ff6b6b"), ("A", "#ffa94d"), ("B", "#ffd43b"), ("C", "#a9e34b"), ("D", "#4dabf7")]
TIER_COLORS = [("Red", "#ff6b6b"), ("Orange", "#ffa94d"), ("Yellow", "#ffd43b"), ("Green", "#a9e34b"),
               ("Teal", "#38d9a9"), ("Blue", "#4dabf7"), ("Violet", "#9775fa"), ("Pink", "#f783ac"),
               ("Gray", "#adb5bd")]


def tier_dims(zoom):
    """Size of a cover at the given zoom."""
    return max(24, round(TIER_W * zoom)), max(32, round(TIER_H * zoom))


def tier_move(rows, gid, row_index, pos):
    """Move a game to row row_index (None = 'unranked') at position pos."""
    old_row = old_pos = None
    for i, r in enumerate(rows):
        if gid in r["ids"]:
            old_row, old_pos = i, r["ids"].index(gid)
            r["ids"].remove(gid)
    if row_index is not None:
        ids = rows[row_index]["ids"]
        if old_row == row_index and old_pos < pos:
            pos -= 1
        ids.insert(max(0, min(pos, len(ids))), gid)


def tier_drop_index(x, y, cols, n, cw, ch):
    """Insertion position according to where the cover is dropped inside a row (cw/ch = cell size)."""
    col = max(0, min(int((x - TIER_PAD) // cw), cols - 1))
    row = max(0, int((y - TIER_PAD) // ch))
    inside = (x - TIER_PAD) - col * cw
    idx = row * cols + col + (1 if inside > cw / 2 else 0)
    return max(0, min(idx, n))


_TIER_PIX = {}


def tier_pixmap(g):
    """Cover at double size, so the zoom looks sharp."""
    BW, BH = TIER_W * 2, TIER_H * 2
    key = g.get("cover") or ("sin:" + g["id"])
    if key in _TIER_PIX:
        return _TIER_PIX[key]
    pm = QPixmap(str(COVERS_DIR / g["cover"])) if g.get("cover") else QPixmap()
    if pm.isNull():
        def draw(p):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#232840"))
            p.drawRoundedRect(QRectF(0, 0, BW, BH), 16, 16)
            p.setPen(QColor("#c9ccdd"))
            f = QFont(p.font())
            f.setPointSize(16)
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRect(12, 12, BW - 24, BH - 24), A_CENTER | Qt.TextFlag.TextWordWrap.value, g["name"])
        out = make_pixmap(BW, BH, draw)
    else:
        sc = pm.scaled(BW, BH, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                       Qt.TransformationMode.SmoothTransformation)
        out = sc.copy((sc.width() - BW) // 2, (sc.height() - BH) // 2, BW, BH)
    _TIER_PIX[key] = out
    return out


class CoverLabel(QLabel):
    """Draggable cover (it scales with the zoom on its own)."""
    def __init__(self, gid, pix, tip, w, h, rerun=False, mark=False, platinum=False, mark_plat=False,
                 dropped=False, mark_dropped=False):
        super().__init__()
        self.gid = gid
        self.dropped = dropped              # the game is Dropped
        self.mark_dropped = mark_dropped    # draw the DROPPED tag on the cover (top left)
        self.rerun = rerun      # the game is flagged as a rerun
        self.mark = mark        # draw the RERUN tag on top of the cover
        self.platinum = platinum        # the platinum trophy was earned
        self.mark_plat = mark_plat      # draw the platinum badge on top of the cover
        self._press = None
        self.setPixmap(pix)
        self.setScaledContents(True)
        self.setFixedSize(w, h)
        self.setToolTip(tip)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def set_mark(self, on):
        self.mark = on
        self.update()

    def set_mark_plat(self, on):
        self.mark_plat = on
        self.update()

    def set_mark_dropped(self, on):
        self.mark_dropped = on
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        show_rerun = self.rerun and self.mark
        show_plat = self.platinum and self.mark_plat
        show_drop = self.dropped and self.mark_dropped
        if not (show_rerun or show_plat or show_drop):
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if show_drop:   # top left corner (the platinum badge is on the right and RERUN at the bottom)
            spx = max(6, round(self.width() * 0.10))
            label = tr("DROPPED")
            sf = QFont(p.font())
            sf.setBold(True)
            while True:   # shrink the tag until it fits inside the cover (small zoom)
                sf.setPixelSize(spx)
                sw = QFontMetrics(sf).horizontalAdvance(label) + max(4, spx)
                if sw <= self.width() - 8 or spx <= 4:
                    break
                spx -= 1
            p.setFont(sf)
            sh = spx + 7
            sy = 4
            if show_plat:   # not on top of the platinum badge: if they would touch, go below it
                psz = max(14, round(self.width() * 0.22))
                if 4 + sw > self.width() - psz - 6:
                    sy = psz + 8
            sr = QRect(4, sy, sw, sh)
            sp = QPainterPath()
            sp.addRoundedRect(QRectF(sr), sh / 2, sh / 2)
            p.fillPath(sp, QColor(STATUS_COLORS["Dropeado"]))
            p.setPen(QColor("#10121b"))
            p.drawText(sr, A_CENTER, label)
        if show_plat:   # top right corner; scales with the cover (zoom)
            sz = max(14, round(self.width() * 0.22))
            draw_platinum(p, QRect(self.width() - sz - 3, 3, sz, sz))
        if not show_rerun:
            p.end()
            return
        px = max(7, round(self.width() * 0.12))      # the tag scales with the cover (zoom)
        f = QFont(p.font())
        f.setPixelSize(px)
        f.setBold(True)
        p.setFont(f)
        tw = QFontMetrics(f).horizontalAdvance("RERUN") + px
        th = px + 8
        r = QRect((self.width() - tw) // 2, self.height() - th - 5, tw, th)
        path = QPainterPath()
        path.addRoundedRect(QRectF(r), th / 2, th / 2)
        p.fillPath(path, QColor(ACCENT))
        p.setPen(QColor("#ffffff"))
        p.drawText(r, A_CENTER, "RERUN")
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if self._press is None or not (e.buttons() & Qt.MouseButton.LeftButton):
            return
        if (e.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        hot = self._press
        self._press = None
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(TIER_MIME + self.gid)
        drag.setMimeData(mime)
        drag.setPixmap(self.pixmap().scaled(self.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))
        drag.setHotSpot(hot)
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, e):
        self._press = None


class TierRow(QFrame):
    """Row where covers are dropped. index=None is the 'unranked' tray."""
    def __init__(self, dlg, index):
        super().__init__()
        self.dlg = dlg
        self.index = index
        self.cells = []
        self.setObjectName("tierRow")
        self.setAcceptDrops(True)
        self.setMinimumHeight(dlg.cell()[1] + TIER_PAD)

    def cols(self):
        return max(1, (self.width() - TIER_PAD) // self.dlg.cell()[0])

    def set_cells(self, labels):
        self.cells = labels
        for c in labels:
            if c.parent() is not self:
                c.setParent(self)
            c.show()
        self.layout_cells()

    def layout_cells(self):
        cw, ch = self.dlg.cell()
        cols = self.cols()
        for i, c in enumerate(self.cells):
            c.move(TIER_PAD + (i % cols) * cw, TIER_PAD + (i // cols) * ch)
        rows = max(1, -(-len(self.cells) // cols))
        self.setMinimumHeight(TIER_PAD + rows * ch)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.layout_cells()

    def _ok(self, e):
        return e.mimeData().hasText() and e.mimeData().text().startswith(TIER_MIME)

    def dragEnterEvent(self, e):
        if self._ok(e):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if self._ok(e):
            e.acceptProposedAction()
            self.dlg.autoscroll(self.mapToGlobal(e.position().toPoint()))

    def dropEvent(self, e):
        if not self._ok(e):
            return
        gid = e.mimeData().text()[len(TIER_MIME):]
        pos = e.position().toPoint()
        cw, ch = self.dlg.cell()
        idx = tier_drop_index(pos.x(), pos.y(), self.cols(), len(self.cells), cw, ch)
        e.acceptProposedAction()
        self.dlg.move_card(gid, self.index, idx)


class TierLabel(QLabel):
    """Row name: double click = rename, right click = row options."""
    def __init__(self, dlg, idx):
        super().__init__()
        self.dlg = dlg
        self.idx = idx
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setFixedWidth(104)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tr("Double-click: rename · Right-click: row options"))

    def mouseDoubleClickEvent(self, e):
        self.dlg.rename_row(self.idx)

    def contextMenuEvent(self, e):
        self.dlg.row_menu(self.idx, e.globalPos())


class FlowLayout(QLayout):
    """
    Lays widgets out from left to right and wraps them onto the next line when there is no room, so
    buttons are never squeezed or clipped in a narrow window. If everything fits on one line, the items
    from index `split_at` onwards are pushed to the right edge.
    """
    def __init__(self, hspacing=8, vspacing=8):
        super().__init__()
        self._items = []
        self._h, self._v = hspacing, vspacing
        self.split_at = None

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def one_line_width(self):
        """Width needed to show every item on a single line."""
        n = len(self._items)
        return sum(it.sizeHint().width() for it in self._items) + self._h * max(0, n - 1)

    def minimumSize(self):
        w = max((it.minimumSize().width() for it in self._items), default=0)
        h = max((it.sizeHint().height() for it in self._items), default=0)
        return QSize(w, h)

    def _arrange(self, rect, apply):
        items = self._items
        if not items:
            return 0
        sizes = [it.sizeHint() for it in items]
        row_h = max(sz.height() for sz in sizes)
        total = sum(sz.width() for sz in sizes) + self._h * (len(items) - 1)

        def place(it, x, y, sz):
            if apply:   # center each item vertically inside its line
                it.setGeometry(QRect(x, y + (row_h - sz.height()) // 2, sz.width(), sz.height()))

        if total <= rect.width():   # one line (the right group goes to the right edge)
            right_from = self.split_at if self.split_at is not None else len(items)
            x = rect.x()
            for i, (it, sz) in enumerate(zip(items, sizes)):
                if i == right_from:
                    right_w = sum(z.width() for z in sizes[i:]) + self._h * (len(items) - i - 1)
                    x = max(x, rect.x() + rect.width() - right_w)
                place(it, x, rect.y(), sz)
                x += sz.width() + self._h
            return row_h
        x, y = rect.x(), rect.y()   # several lines
        for it, sz in zip(items, sizes):
            if x > rect.x() and x + sz.width() > rect.x() + rect.width():
                x = rect.x()
                y += row_h + self._v
            place(it, x, y, sz)
            x += sz.width() + self._h
        return y + row_h - rect.y()


class TierListDialog(QDialog):
    def __init__(self, parent, year, games):
        super().__init__(parent)
        self.setObjectName("tierDialog")
        self.year = year
        self.games = {g["id"]: g for g in games}
        saved = load_json(TIER_FILE, {}).get(str(year), {})
        self.rows = saved.get("rows") or [{"name": n, "color": c, "ids": []} for n, c in DEFAULT_TIERS]
        self.zoom = saved.get("zoom") if saved.get("zoom") in ZOOMS else 1.0
        self.has_reruns = any(g.get("rerun") for g in games)
        self.has_plat = any(g.get("platinum") for g in games)
        self.has_dropped = any(g.get("status") == "Dropeado" for g in games)
        self.hide_dropped = bool(saved.get("hide_dropped")) and self.has_dropped
        self.mark_dropped = bool(saved.get("mark_dropped")) and self.has_dropped
        self.hide_reruns = bool(saved.get("hide_reruns")) and self.has_reruns
        self.mark_reruns = bool(saved.get("mark_reruns")) and self.has_reruns
        self.mark_plat = bool(saved.get("mark_platinum")) and self.has_plat
        self.covers = {}
        self.row_boxes = []
        self.row_widgets = []
        self.setWindowTitle(tr("Tier list · {year} list", year=year))
        # resizable window: maximize/minimize button and corner grip
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(760, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)
        t = QLabel(tr("Tier list {year}", year=year))
        t.setObjectName("title")
        self.hint = QLabel(tr("Drag the covers to their row. Use ▲ ▼ to move a row and ⚙ for its options (color, "
                              "rename, add, clear, delete); double-click a row name to rename it. Deleting a row "
                              "never deletes games: they go back to “Unranked”. Zoom: − / + buttons or Ctrl + mouse wheel."))
        self.hint.setObjectName("subtitle")
        self.hint.setWordWrap(True)
        root.addWidget(t)
        root.addWidget(self.hint)

        tools = FlowLayout(8, 8)   # wraps onto a second line in a narrow window
        b_out = make_btn("−", "ghost", tr("Zoom out (Ctrl + wheel down)"))
        b_in = make_btn("+", "ghost", tr("Zoom in (Ctrl + wheel up)"))
        for b in (b_out, b_in):
            b.setFixedWidth(44)
            b.setStyleSheet("padding: 0px; font-size: 16px;")
        b_out.clicked.connect(lambda _=False: self.zoom_step(-1))
        b_in.clicked.connect(lambda _=False: self.zoom_step(1))
        self.zoom_lbl = QLabel(f"{round(self.zoom * 100)}%")
        self.zoom_lbl.setMinimumWidth(48)
        self.zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tools.addWidget(b_out)
        tools.addWidget(self.zoom_lbl)
        tools.addWidget(b_in)
        for text, name, fn in ((tr("+ Row"), "ghost", self.add_row), (tr("Reset"), "ghost", self.reset)):
            b = make_btn(text, name)
            b.clicked.connect(fn)
            tools.addWidget(b)
        self.btn_hide = make_btn(tr("🔁  Hide reruns"), "ghost",
                                 tr("Hide the games marked as Rerun (they keep their place in the tier list)"))
        self.btn_mark = make_btn(tr("🏷  Mark reruns"), "ghost",
                                 tr("Show a RERUN tag at the bottom of the covers of games marked as Rerun"))
        self.btn_plat = make_btn(tr("🏆  Mark platinums"), "ghost",
                                 tr("Show a platinum trophy on the covers of the games with the platinum earned"))
        self.btn_hide_drop = make_btn(tr("🚫  Hide dropped"), "ghost",
                                      tr("Hide the games with Dropped status (they keep their place in the tier list)"))
        self.btn_mark_drop = make_btn(tr("🏷  Mark dropped"), "ghost",
                                      tr("Show a DROPPED tag at the top left of the covers of the dropped games"))
        no_rerun = tr("No game in this list is marked as Rerun")
        no_plat = tr("No game in this list has the platinum earned")
        no_drop = tr("No game in this list is Dropped")
        for b, on, fn, has, msg in ((self.btn_hide, self.hide_reruns, self.toggle_hide, self.has_reruns, no_rerun),
                                    (self.btn_mark, self.mark_reruns, self.toggle_mark, self.has_reruns, no_rerun),
                                    (self.btn_plat, self.mark_plat, self.toggle_plat, self.has_plat, no_plat),
                                    (self.btn_hide_drop, self.hide_dropped, self.toggle_hide_dropped,
                                     self.has_dropped, no_drop),
                                    (self.btn_mark_drop, self.mark_dropped, self.toggle_mark_dropped,
                                     self.has_dropped, no_drop)):
            b.setCheckable(True)
            b.setChecked(on)
            b.clicked.connect(fn)
            if not has:
                b.setEnabled(False)
                b.setToolTip(msg)
            tools.addWidget(b)
        tools.split_at = tools.count()   # from here on (save / open / export / close) the buttons go to the right
        for text, name, fn, tip in (
            (tr("Save photo to {year}", year=year), "soft", self.save_photo,
             tr("Saves the tier list photo into the {year} list (it is also saved automatically on close)", year=year)),
            (tr("Open photo"), "ghost", self.open_photo, tr("Opens this year's saved photo")),
            (tr("Export…"), "ghost", self.export, tr("Save the photo to another folder")),
            (tr("Close"), "primary", self.accept, ""),
        ):
            b = make_btn(text, name, tip)
            b.clicked.connect(lambda _=False, fn=fn: fn())
            tools.addWidget(b)
        root.addLayout(tools)
        self._fit_window(tools)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.tiers_box = QWidget()
        self.tiers_layout = QVBoxLayout(self.tiers_box)
        self.tiers_layout.setContentsMargins(0, 0, 0, 0)
        self.tiers_layout.setSpacing(6)
        self.scroll.setWidget(self.tiers_box)

        self.pool = TierRow(self, None)
        self.pool_scroll = QScrollArea()
        self.pool_scroll.setWidgetResizable(True)
        self.pool_scroll.setMinimumHeight(110)
        self.pool_scroll.setWidget(self.pool)
        pool_box = QWidget()
        pb = QVBoxLayout(pool_box)
        pb.setContentsMargins(0, 0, 0, 0)
        pb.setSpacing(6)
        lab = QLabel(tr("Unranked"))
        lab.setObjectName("section")
        pb.addWidget(lab)
        pb.addWidget(self.pool_scroll)

        # draggable splitter between the rows and the tray
        self.split = QSplitter(Qt.Orientation.Vertical)
        self.split.setChildrenCollapsible(False)
        self.split.addWidget(self.scroll)
        self.split.addWidget(pool_box)
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 0)
        self.split.setSizes([620, 250])
        root.addWidget(self.split, 1)

        # Ctrl + wheel = zoom (over both scroll areas)
        self.scroll.viewport().installEventFilter(self)
        self.pool_scroll.viewport().installEventFilter(self)
        for keys in (QKeySequence(QKeySequence.StandardKey.ZoomIn), QKeySequence("Ctrl+=")):
            QShortcut(keys, self).activated.connect(lambda: self.zoom_step(1))
        QShortcut(QKeySequence(QKeySequence.StandardKey.ZoomOut), self).activated.connect(lambda: self.zoom_step(-1))
        QShortcut(QKeySequence("Ctrl+0"), self).activated.connect(lambda: self.set_zoom(1.0))

        self.build_rows()

    # ---- zoom ----
    def cell(self):
        w, h = tier_dims(self.zoom)
        return w + TIER_PAD, h + TIER_PAD

    def set_zoom(self, z):
        if z == self.zoom:
            return
        self.zoom = z
        w, h = tier_dims(z)
        for c in self.covers.values():
            c.setFixedSize(w, h)
        for trow in self.row_widgets + [self.pool]:
            trow.layout_cells()
        self.zoom_lbl.setText(f"{round(z * 100)}%")
        self.save()

    def zoom_step(self, d):
        i = min(range(len(ZOOMS)), key=lambda k: abs(ZOOMS[k] - self.zoom))
        self.set_zoom(ZOOMS[max(0, min(len(ZOOMS) - 1, i + d))])

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.Wheel and (e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.zoom_step(1 if e.angleDelta().y() > 0 else -1)
            return True
        return super().eventFilter(obj, e)

    # ---- build ----
    def cover(self, gid):
        c = self.covers.get(gid)
        if c is None:
            g = self.games[gid]
            w, h = tier_dims(self.zoom)
            c = self.covers[gid] = CoverLabel(gid, tier_pixmap(g), g["name"], w, h,
                                              rerun=bool(g.get("rerun")), mark=self.mark_reruns,
                                              platinum=bool(g.get("platinum")), mark_plat=self.mark_plat,
                                              dropped=g.get("status") == "Dropeado", mark_dropped=self.mark_dropped)
        return c

    def style_label(self, lab, row):
        lab.setText(row["name"])
        lab.setStyleSheet(f"background: {row['color']}; color: #10121b; font-size: 20px; font-weight: 800; "
                          f"border-radius: 10px; padding: 4px;")

    def build_rows(self):
        for c in self.covers.values():   # covers are kept: they are taken out of the rows before the rows are deleted
            c.setParent(self)
            c.hide()
        while self.tiers_layout.count():
            w = self.tiers_layout.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self.row_boxes, self.row_widgets = [], []
        for i, r in enumerate(self.rows):
            box = QWidget()
            h = QHBoxLayout(box)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            lab = TierLabel(self, i)
            self.style_label(lab, r)
            trow = TierRow(self, i)
            h.addWidget(lab)
            h.addWidget(trow, 1)
            ctrl = QWidget()
            ctrl.setFixedWidth(TIER_CTRL_W)
            cl = QVBoxLayout(ctrl)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(2)
            cl.addStretch(1)
            up = self._ctl("▲", tr("Move row up"), lambda _=False, i=i: self.move_row(i, -1))
            up.setEnabled(i > 0)
            gear = self._ctl("⚙", tr("Row options: color, rename, move, add, clear, delete"), None)
            gear.clicked.connect(lambda _=False, i=i, b=gear: self.row_menu(i, b.mapToGlobal(b.rect().bottomLeft())))
            down = self._ctl("▼", tr("Move row down"), lambda _=False, i=i: self.move_row(i, 1))
            down.setEnabled(i < len(self.rows) - 1)
            for b in (up, gear, down):
                cl.addWidget(b)
            cl.addStretch(1)
            h.addWidget(ctrl)
            self.tiers_layout.addWidget(box)
            self.row_boxes.append(box)
            self.row_widgets.append(trow)
        self.tiers_layout.addStretch(1)
        self.refill()

    def _fit_window(self, tools):
        """Open wide enough for the whole toolbar to fit on one line (no 'Close' button on a second line)."""
        need = tools.one_line_width() + 24 + 24 + 40       # dialog margins + room for the scroll bar and a little slack
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(min(max(1280, need), screen.width() - 40), min(900, screen.height() - 60))

    def _hidden(self, gid):
        g = self.games[gid]
        return ((self.hide_reruns and bool(g.get("rerun")))
                or (self.hide_dropped and g.get("status") == "Dropeado"))

    def refill(self):
        present = set(self.games)
        hidden = {i for i in present if self._hidden(i)}
        placed = set()
        for r, trow in zip(self.rows, self.row_widgets):
            # hidden games (reruns, dropped) stay in r["ids"] (they keep their place); they are just not drawn
            r["ids"] = [i for i in r["ids"] if i in present and i not in placed]
            placed.update(r["ids"])
            trow.set_cells([self.cover(i) for i in r["ids"] if i not in hidden])
        pool_ids = sorted((i for i in present if i not in placed and i not in hidden),
                          key=lambda i: _fold(self.games[i]["name"]))
        self.pool.set_cells([self.cover(i) for i in pool_ids])
        for i in hidden:
            if i in self.covers:
                self.covers[i].hide()

    def toggle_hide(self, on):
        self.hide_reruns = bool(on)
        self.save()
        self.refill()

    def toggle_mark(self, on):
        self.mark_reruns = bool(on)
        self.save()
        for c in self.covers.values():
            c.set_mark(self.mark_reruns)

    def toggle_hide_dropped(self, on):
        self.hide_dropped = bool(on)
        self.save()
        self.refill()

    def toggle_mark_dropped(self, on):
        self.mark_dropped = bool(on)
        self.save()
        for c in self.covers.values():
            c.set_mark_dropped(self.mark_dropped)

    def toggle_plat(self, on):
        self.mark_plat = bool(on)
        self.save()
        for c in self.covers.values():
            c.set_mark_plat(self.mark_plat)

    # ---- actions ----
    def save(self):
        data = load_json(TIER_FILE, {})
        data[str(self.year)] = {"rows": self.rows, "zoom": self.zoom,
                                "hide_reruns": self.hide_reruns, "mark_reruns": self.mark_reruns,
                                "mark_platinum": self.mark_plat,
                                "hide_dropped": self.hide_dropped, "mark_dropped": self.mark_dropped}
        ensure_dirs()
        save_json(TIER_FILE, data)

    def move_card(self, gid, row_index, pos):
        if row_index is not None and (self.hide_reruns or self.hide_dropped):
            # pos counts only the visible covers: translate it to a position in the full list (hidden ones included)
            ids = self.rows[row_index]["ids"]
            vis = [i for i in ids if not self._hidden(i)]
            pos = ids.index(vis[pos]) if pos < len(vis) else len(ids)
        tier_move(self.rows, gid, row_index, pos)
        self.save()
        QTimer.singleShot(0, self.refill)   # after the drag ends

    def autoscroll(self, gpos):
        for sa in (self.scroll, self.pool_scroll):
            vp = sa.viewport()
            p = vp.mapFromGlobal(gpos)
            if 0 <= p.x() <= vp.width() and -20 <= p.y() <= vp.height() + 20:
                bar = sa.verticalScrollBar()
                if p.y() < 36:
                    bar.setValue(bar.value() - 20)
                elif p.y() > vp.height() - 36:
                    bar.setValue(bar.value() + 20)

    def rename_row(self, i):
        text, ok = QInputDialog.getText(self, tr("Rename row"), tr("Row name:"), text=self.rows[i]["name"])
        if ok and text.strip():
            self.rows[i]["name"] = text.strip()[:14]
            self.save()
            self.build_rows()

    def _ctl(self, glyph, tip, fn):
        b = QPushButton(glyph)
        b.setObjectName("tierCtl")
        b.setFixedSize(TIER_CTRL_W - 2, 26)
        b.setToolTip(tip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if fn:
            b.clicked.connect(fn)
        return b

    def row_menu(self, i, gpos):
        m = QMenu(self)
        style_menu(m)
        a = m.addAction(tr("Rename"))
        a.triggered.connect(lambda _=False: self.rename_row(i))
        sub = m.addMenu(tr("Color"))
        style_menu(sub)
        for name, col in TIER_COLORS:
            act = sub.addAction(tr(name))
            px = QPixmap(14, 14)
            px.fill(QColor(col))
            act.setIcon(QIcon(px))
            act.triggered.connect(lambda _=False, col=col: self.set_row_color(i, col))
        sub.addSeparator()
        act = sub.addAction(tr("Custom color…"))
        act.triggered.connect(lambda _=False: self.pick_row_color(i))
        m.addSeparator()
        up = m.addAction(tr("Move row up"))
        up.setEnabled(i > 0)
        up.triggered.connect(lambda _=False: self.move_row(i, -1))
        down = m.addAction(tr("Move row down"))
        down.setEnabled(i < len(self.rows) - 1)
        down.triggered.connect(lambda _=False: self.move_row(i, 1))
        above = m.addAction(tr("Add row above"))
        above.triggered.connect(lambda _=False: self.add_row_at(i))
        below = m.addAction(tr("Add row below"))
        below.triggered.connect(lambda _=False: self.add_row_at(i + 1))
        m.addSeparator()
        c = m.addAction(tr("Clear row (covers go back to “Unranked”)"))
        c.setEnabled(bool(self.rows[i]["ids"]))
        c.triggered.connect(lambda _=False: self.clear_row(i))
        d = m.addAction(tr("Delete row (its covers go back to “Unranked”)"))
        d.setEnabled(len(self.rows) > 1)
        d.triggered.connect(lambda _=False: self.delete_row(i))
        m.exec(gpos)

    def set_row_color(self, i, col):
        self.rows[i]["color"] = col
        self.save()
        self.build_rows()

    def pick_row_color(self, i):
        col = QColorDialog.getColor(QColor(self.rows[i]["color"]), self, tr("Row color"))
        if col.isValid():
            self.set_row_color(i, col.name())

    def move_row(self, i, d):
        j = i + d
        if 0 <= j < len(self.rows):
            self.rows[i], self.rows[j] = self.rows[j], self.rows[i]
            self.save()
            self.build_rows()

    def add_row_at(self, i):
        self.rows.insert(i, {"name": tr("New"), "color": "#adb5bd", "ids": []})
        self.save()
        self.build_rows()

    def clear_row(self, i):
        self.rows[i]["ids"] = []   # covers are NOT deleted: they go back to 'unranked'
        self.save()
        self.refill()

    def delete_row(self, i):
        if len(self.rows) > 1:
            del self.rows[i]   # the row is deleted, but its covers go back to 'unranked' (the games stay in the list)
            self.save()
            self.build_rows()

    def add_row(self, *_):
        self.rows.append({"name": tr("New"), "color": "#adb5bd", "ids": []})
        self.save()
        self.build_rows()

    def reset(self, *_):
        if not confirm_box(self, tr("Reset tier list"), tr("Move all covers back to “Unranked”?"), tr("Reset")):
            return
        for r in self.rows:
            r["ids"] = []
        self.save()
        self.refill()

    # ---- tier list photo ----
    def render_photo(self):
        """Tier list image (with title and background), exactly as it looks now."""
        last = self.row_boxes[-1].geometry().bottom() + 1 if self.row_boxes else self.tiers_box.height()
        body = self.tiers_box.grab(QRect(0, 0, max(50, self.tiers_box.width() - TIER_CTRL_W - 8), last))
        dpr = body.devicePixelRatio()
        head = 56
        out = QPixmap(body.width(), body.height() + int(head * dpr))
        out.setDevicePixelRatio(dpr)
        out.fill(QColor(BG))
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = QFont(p.font())
        f.setPointSize(18)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(TH["TITLE"]))
        p.drawText(QRect(4, 0, int(body.width() / dpr) - 8, head), A_LEFT, tr("Tier list {year}", year=self.year))
        p.drawPixmap(0, head, body)
        p.end()
        return out

    def photo_path(self):
        return TIER_PHOTOS / f"tierlist_{self.year}.png"

    def save_photo(self, silent=False):
        """Save the photo inside the app's data, tied to this year."""
        if not any(r["ids"] for r in self.rows):
            if not silent:
                self.hint.setText(tr("Place a cover in a row before saving the photo."))
            return False
        TIER_PHOTOS.mkdir(parents=True, exist_ok=True)
        ok_ = self.render_photo().save(str(self.photo_path()), "PNG")
        if not silent:
            self.hint.setText(tr("Photo saved in the {year} list: {path}", year=self.year, path=self.photo_path()) if ok_
                              else tr("Could not save the photo."))
        return ok_

    def open_photo(self):
        path = self.photo_path()
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            self.hint.setText(tr("There is no saved photo for this year yet: press “Save photo”."))

    def export(self, *_):
        path, _f = QFileDialog.getSaveFileName(self, tr("Export tier list"), f"tierlist_{self.year}.png",
                                               tr("PNG image (*.png)"))
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        self.hint.setText(tr("Image saved to {path}", path=path) if self.render_photo().save(path, "PNG")
                          else tr("Could not save the image."))

    def done(self, r):
        try:
            self.save_photo(silent=True)   # when it closes, the photo is saved for that year
        except Exception:
            pass
        super().done(r)


class TransferDialog(QDialog):
    """Move or copy several games of a list (by default the Planned ones) to another year's list."""
    def __init__(self, parent, year, year_games, years, all_games, preset=None):
        super().__init__(parent)
        self.year = year
        self.year_games = year_games
        self.all_games = all_games
        self.preset = preset   # games selected by hand in the main window (then there is no "Which games")
        self.setWindowTitle(tr("Move or copy games"))
        self.setMinimumWidth(500)
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 20)
        root.setSpacing(12)
        t = QLabel(tr("Pass the {n} selected games to another list", n=len(preset)) if preset
                   else tr("Pass games from the {year} list to another one", year=year))
        t.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {TH['TITLE']};")
        t.setWordWrap(True)
        root.addWidget(t)
        hint = QLabel(tr("Useful at the end of the year: what you did not get to play goes on to the next "
                         "list, and the completed ones stay in this one."))
        hint.setObjectName("subtitle")
        hint.setWordWrap(True)
        if preset:
            names = ", ".join(g["name"] for g in preset[:6]) + ("…" if len(preset) > 6 else "")
            hint.setText(names)
        root.addWidget(hint)

        sec = QLabel(tr("Which games"))
        sec.setObjectName("section")
        sec.setVisible(not preset)
        root.addWidget(sec)
        self.checks = {}
        for s in STATUSES if not preset else []:
            n = sum(1 for g in year_games if g["status"] == s)
            c = QCheckBox(f"{status_label(s)}  ({n})")
            c.setChecked(s == "Planeado" and n > 0)
            c.setEnabled(n > 0)
            c.setCursor(Qt.CursorShape.PointingHandCursor)
            c.setStyleSheet(status_check_style(STATUS_COLORS[s]))
            c.toggled.connect(self.update_summary)
            self.checks[s] = c
            root.addWidget(c)

        sec2 = QLabel(tr("To the list"))
        sec2.setObjectName("section")
        root.addWidget(sec2)
        self.target = make_combo()
        for y in sorted(set(y for y in years if y != year) | {year + 1}):
            self.target.addItem(tr("List {year}", year=y) + ("" if y in years else tr("  (new)")), y)
        self.target.setCurrentIndex(max(self.target.findData(year + 1), 0))
        self.target.currentIndexChanged.connect(self.update_summary)
        root.addWidget(self.target)

        sec3 = QLabel(tr("How"))
        sec3.setObjectName("section")
        root.addWidget(sec3)
        self.mode = make_combo()
        self.mode.addItem(tr("Move (they leave the {year} list)", year=year), False)
        self.mode.addItem(tr("Copy (they also stay in the {year} list)", year=year), True)
        self.mode.currentIndexChanged.connect(self.update_summary)
        root.addWidget(self.mode)

        self.summary = QLabel("")
        self.summary.setObjectName("indexPreview")
        self.summary.setWordWrap(True)
        self.summary.setMinimumHeight(66)   # room for two lines (the second one only shows up sometimes)
        root.addWidget(self.summary)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_b = bb.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_b.setObjectName("primary")
        cancel_b = bb.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_b.setText(tr("Cancel"))
        cancel_b.setObjectName("ghost")
        for b in (self.ok_b, cancel_b):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addSpacing(6)
        root.addWidget(bb)
        self.update_summary()

    def chosen(self):
        if self.preset:
            return list(self.preset)
        on = {s for s, c in self.checks.items() if c.isChecked()}
        return [g for g in self.year_games if g["status"] in on]

    def result_values(self):
        return self.target.currentData(), bool(self.mode.currentData()), self.chosen()

    def update_summary(self, *_):
        target, copy_mode, games = self.result_values()
        have = {_fold(g["name"]) for g in self.all_games if g.get("year") == target}
        dup = sum(1 for g in games if _fold(g["name"]) in have)
        n = len(games) - dup
        key = "Games that will be copied to the {year} list: {n}" if copy_mode else "Games that will be moved to the {year} list: {n}"
        text = tr(key, n=n, year=target)
        if dup:
            text += "\n" + tr("Already in that list (left as they are): {n}", n=dup)
        self.summary.setText(text)
        self.ok_b.setText(tr("Copy") if copy_mode else tr("Move"))
        self.ok_b.setEnabled(n > 0)


def confirm_box(parent, title, text, yes_text):
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setText(text)
    yes = box.addButton(yes_text, QMessageBox.ButtonRole.DestructiveRole)
    yes.setObjectName("danger")
    no = box.addButton(tr("Cancel"), QMessageBox.ButtonRole.RejectRole)
    no.setObjectName("ghost")
    box.setDefaultButton(no)
    box.exec()
    return box.clickedButton() is yes


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Backup (a .zip with games, covers, tier lists and settings)
# --------------------------------------------------------------------------
BACKUP_MARK = "backup_info.json"
BACKUP_DIRS = ("covers", "tierlists")
PERSONAL_CFG = ("geometry", "sidebar_w", "sidebar_hidden", "filters")   # settings of YOUR window: they are not part of the backup
BACKUP_MAX_BYTES = 1024 ** 3


def normalize_game(g):
    """Fill in any missing fields (games saved by older versions)."""
    g.setdefault("platform", "")
    g.setdefault("platinum", False)
    g.setdefault("hltb_id", None)
    g.setdefault("rerun", False)
    for k in ("hours_main", "hours_extra", "hours_100", "user_score", "meta_platform"):
        g.setdefault(k, None)
    g.setdefault("meta_other", False)
    if not isinstance(g.get("year"), int) or isinstance(g.get("year"), bool):
        added = g.get("added")
        g["year"] = time.localtime(added if isinstance(added, (int, float)) else time.time()).tm_year
    return g


def sanitize_imported(g):
    """Game coming from someone else's backup: check everything later used to draw or to touch files."""
    g = normalize_game(dict(g))
    g["id"] = str(g.get("id") or uuid.uuid4().hex)
    g["name"] = str(g.get("name") or "").strip() or tr("Unnamed")
    if g.get("status") not in STATUSES:
        g["status"] = "Planeado"
    for k in ("my_score", "meta_score", "user_score", "hours", "hours_main", "hours_extra", "hours_100"):
        v = g.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            g[k] = None
    g["platinum"] = bool(g.get("platinum"))
    g["rerun"] = bool(g.get("rerun"))
    g["meta_other"] = bool(g.get("meta_other"))
    if g.get("meta_platform") not in PLATFORMS:
        g["meta_platform"] = None
    g["notes"] = str(g.get("notes") or "")
    if not isinstance(g.get("platform"), str) or (g["platform"] and g["platform"] not in PLATFORMS):
        g["platform"] = ""
    if not isinstance(g.get("added"), (int, float)):
        g["added"] = time.time()
    cov = g.get("cover")
    # the cover name is later used as a path: only a plain file name is accepted
    if not isinstance(cov, str) or PurePosixPath(cov).name != cov or "\\" in cov or cov in ("", ".", ".."):
        g["cover"] = ""
    return g


def backup_member_ok(name):
    pp = PurePosixPath(name)
    if pp.is_absolute() or ".." in pp.parts or "\\" in name or ":" in name:
        return False
    if name in ("games.json", "config.json", "tierlists.json", BACKUP_MARK):
        return True
    return len(pp.parts) == 2 and pp.parts[0] in BACKUP_DIRS and pp.parts[1] not in ("", ".")


def write_backup(path, games, config):
    cfg = {k: v for k, v in config.items() if k not in PERSONAL_CFG}
    info = {"app": "mi_backlog_juegos", "format": 1, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "games": len(games)}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(BACKUP_MARK, json.dumps(info, ensure_ascii=False, indent=2))
        z.writestr("config.json", json.dumps(cfg, ensure_ascii=False, indent=2))
        z.writestr("games.json", json.dumps(games, ensure_ascii=False, indent=2))
        if TIER_FILE.exists():
            z.write(TIER_FILE, "tierlists.json")
        for d in BACKUP_DIRS:
            folder = DATA_DIR / d
            if folder.is_dir():
                for f in sorted(folder.iterdir()):
                    if f.is_file():
                        z.write(f, f"{d}/{f.name}")


def check_backup(z):
    """Check that the zip is a backup of this app. Raises ValueError if it is not."""
    names = z.namelist()
    if BACKUP_MARK not in names:
        raise ValueError(tr("That file is not a My Game Backlog backup."))
    try:
        if json.loads(z.read(BACKUP_MARK).decode("utf-8")).get("app") != "mi_backlog_juegos":
            raise ValueError
    except Exception:
        raise ValueError(tr("That file is not a My Game Backlog backup."))
    if sum(i.file_size for i in z.infolist()) > BACKUP_MAX_BYTES:
        raise ValueError(tr("The backup is too large."))
    if "games.json" not in names:
        raise ValueError(tr("The backup does not contain the game list."))


def read_json_member(z, name, default):
    if name not in z.namelist():
        return default
    return json.loads(z.read(name).decode("utf-8"))


def extract_member(z, name):
    """Extract a file from the backup into the data folder (never outside it)."""
    if not backup_member_ok(name):
        return False
    target = DATA_DIR / name
    if not str(target.resolve()).startswith(str(DATA_DIR.resolve())):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(z.read(name))
    return True


SORT_OPTIONS = [
    ("Índice", lambda g: index_of(g)),
    ("Mi nota", lambda g: g.get("my_score")),
    ("Nota Metacritic", lambda g: g.get("meta_score")),
    ("Nota usuarios Metacritic", lambda g: g.get("user_score")),
    ("Horas", lambda g: g.get("hours")),
    ("Nombre", lambda g: _fold(g["name"])),
    ("Fecha añadido", lambda g: g.get("added")),
]


class TierPreview(QLabel):
    """Photo of the saved tier list of the current year, for the sidebar. Click = open it / open the tier list."""
    clicked = pyqtSignal()
    MAX_H = 340
    NOMINAL_W = 228   # reference width (the default sidebar width) used to compute the height

    def __init__(self):
        super().__init__()
        self.setObjectName("tierPreview")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setMinimumWidth(1)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._src = None

    def set_photo(self, pm):
        self._src = pm
        self.setMargin(0)
        self.setToolTip(tr("Click to open the photo at full size"))
        # FIXED height from the photo's aspect ratio: it must not depend on the sidebar width. Otherwise,
        # dragging the sidebar would change the content height and the scroll bar would appear and
        # disappear in a loop.
        ratio = pm.height() / max(1, pm.width())
        self.setFixedHeight(min(self.MAX_H, max(60, round(self.NOMINAL_W * ratio))) + 2)
        self._fit()

    def set_empty(self, text):
        self._src = None
        self.setPixmap(QPixmap())
        self.setText(text)
        self.setMargin(10)
        self.setFixedHeight(96)
        self.setToolTip(tr("Click to open the tier list"))

    def _fit(self):
        if self._src is None or self.width() < 20:
            return
        dpr = self.devicePixelRatioF()
        box_h = max(1, self.height() - 2)
        sc = self._src.scaled(QSize(int((self.width() - 2) * dpr), int(box_h * dpr)),
                              Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        sc.setDevicePixelRatio(dpr)
        self.setPixmap(sc)   # the photo is centered inside the frame; the frame's height does not change

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


def _icon_sidebar(color):
    def draw(p):
        _stroke(p, color, 1.6)
        p.drawRoundedRect(QRectF(2, 3, 14, 12), 2.5, 2.5)
        p.drawLine(7, 3, 7, 15)
    return draw


def _icon_grid(color):
    def draw(p):
        _stroke(p, color, 1.6)
        for x, y in ((2.5, 2.5), (10, 2.5), (2.5, 10), (10, 10)):
            p.drawRoundedRect(QRectF(x, y, 5.5, 5.5), 1.5, 1.5)
    return draw


def _icon_list(color):
    def draw(p):
        _stroke(p, color, 1.7)
        for y in (4, 9, 14):
            p.drawLine(3, y, 4, y)      # dot
            p.drawLine(7, y, 16, y)     # line
    return draw


def two_state_icon(maker):
    """Off (gray) and on (light) icons for checkable buttons."""
    ic = QIcon()
    ic.addPixmap(make_pixmap(18, 18, maker(MUTED), dpr=2), QIcon.Mode.Normal, QIcon.State.Off)
    ic.addPixmap(make_pixmap(18, 18, maker(TEXT), dpr=2), QIcon.Mode.Normal, QIcon.State.On)
    return ic


def make_toggle_btn(maker, tip):
    b = QPushButton()
    b.setObjectName("seg")
    b.setCheckable(True)
    b.setIcon(two_state_icon(maker))
    b.setIconSize(QSize(18, 18))
    b.setFixedWidth(42)
    b.setToolTip(tip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    return b


def status_check_style(col):
    chk = ASSETS.get("check_dark")
    img = f'image: url("{chk}");' if chk else ""
    text = col if TH["STATUS_TEXT"] else TEXT
    return (f"QCheckBox {{ color:{text}; font-weight:600; spacing:10px; padding:4px 0; }}"
            f"QCheckBox::indicator {{ width:18px; height:18px; border-radius:6px; border:2px solid {col}; background:transparent; }}"
            f"QCheckBox::indicator:checked {{ background:{col}; {img} }}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        ensure_dirs()
        self.setWindowTitle(tr("My Game Backlog"))
        self.resize(1280, 820)
        self.setMinimumSize(900, 600)
        self.games, self._load_problem = load_games()
        for g in self.games:  # compatibility with games saved before these fields existed
            normalize_game(g)
        self._undo = None          # last deleted game, while its "Undo" bar is visible
        self.config = load_json(CONFIG_FILE, {})
        self.bridge = Bridge(self)        # results of background tasks (updates) reach the window through here
        self.bridge.task.connect(self.on_task)
        self._updating = False            # updating the HowLongToBeat connection
        geo = self.config.get("geometry")   # position, size and whether it was maximized
        if geo:
            try:
                self.restoreGeometry(bytes.fromhex(geo))
            except Exception:
                pass
        base = set(self.config.get("years", [])) or {time.localtime().tm_year}
        self.years = sorted({g["year"] for g in self.games} | base)
        last = self.config.get("last_year")
        self.cur_year = last if last in self.years else self.years[-1]
        self.sort_desc = True
        self.view_mode = self.config.get("view") if self.config.get("view") in ("cards", "list") else "cards"
        self.game_zoom = 1.0   # the card size adapts by itself to the window (see card_grid); no zoom buttons
        self.config.pop("game_zoom", None)
        self._side_w = min(max(int(self.config.get("sidebar_w") or 272), 210), 520)
        self._tier_stamp = None

        # the text and hours filters wait a moment until you stop typing
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(150)
        self._refresh_timer.timeout.connect(self.refresh)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---------- sidebar ----------
        side = QFrame()
        side.setObjectName("sidebar")
        side.setMinimumWidth(210)
        side.setMaximumWidth(520)
        side_outer = QVBoxLayout(side)
        side_outer.setContentsMargins(0, 0, 0, 0)
        side_outer.setSpacing(0)
        side_scroll = QScrollArea()
        side_scroll.setObjectName("sideScroll")
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QFrame.Shape.NoFrame)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)   # no visible scroll bar: if the content does not fit, the mouse wheel scrolls it
        # Nothing inside the sidebar changes height with its width (see TierPreview: its height is fixed),
        # so dragging the sidebar cannot trigger resize loops.
        side_scroll.viewport().setAutoFillBackground(False)
        side_inner = QWidget()
        side_inner.setAutoFillBackground(False)
        side_scroll.setWidget(side_inner)
        side_outer.addWidget(side_scroll)
        sl = QVBoxLayout(side_inner)
        sl.setContentsMargins(22, 18, 22, 16)
        sl.setSpacing(6)

        t = QLabel(tr("🎮  My Backlog"))
        t.setObjectName("title")
        st = QLabel(tr("Higher score and fewer hours = better index"))
        st.setObjectName("subtitle")
        st.setWordWrap(True)
        sl.addWidget(t)
        sl.addWidget(st)

        sl.addWidget(self.section("Status"))
        self.status_checks = {}
        for s in STATUSES:
            c = QCheckBox(status_label(s))
            c.setChecked(True)
            c.setCursor(Qt.CursorShape.PointingHandCursor)
            c.setStyleSheet(status_check_style(STATUS_COLORS[s]))
            c.toggled.connect(self.refresh)
            self.status_checks[s] = c
            sl.addWidget(c)

        sl.addWidget(self.section("Platform"))
        self.plat_combo = make_combo()
        self.plat_combo.addItem(tr("All"), "")
        for pl in PLATFORMS:
            self.plat_combo.addItem(plat_label(pl), pl)
        self.plat_combo.currentIndexChanged.connect(self.refresh)
        sl.addWidget(self.plat_combo)
        self.plat_only = QCheckBox(tr("🏆  Platinum only"))
        self.plat_only.setCursor(Qt.CursorShape.PointingHandCursor)
        self.plat_only.toggled.connect(self.refresh)
        sl.addWidget(self.plat_only)
        self.rerun_only = QCheckBox(tr("🔁  Reruns only"))
        self.rerun_only.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rerun_only.toggled.connect(self.refresh)
        sl.addWidget(self.rerun_only)

        sl.addWidget(self.section("Sort by"))
        self.sort_combo = make_combo()
        self.sort_combo.addItems([sort_label(n) for n, _ in SORT_OPTIONS])
        self.sort_combo.currentIndexChanged.connect(self.refresh)
        sl.addWidget(self.sort_combo)
        self.dir_btn = make_btn("", "ghost")
        self.dir_btn.clicked.connect(self.toggle_dir)
        sl.addWidget(self.dir_btn)
        self.update_dir_btn()

        sl.addWidget(self.section("Hours to finish"))
        hr = QHBoxLayout()
        hr.setSpacing(10)
        self.min_h = NumField(0, 5000, 0, tr("Min h"))
        self.max_h = NumField(0, 5000, 0, tr("Max h"))
        self.min_h.valueChanged.connect(lambda _v: self._refresh_timer.start())
        self.max_h.valueChanged.connect(lambda _v: self._refresh_timer.start())
        hr.addWidget(self.min_h)
        hr.addWidget(self.max_h)
        sl.addLayout(hr)

        self.tier_title = self.section("Tier list")
        sl.addWidget(self.tier_title)
        self.tier_prev = TierPreview()
        self.tier_prev.clicked.connect(self.on_tier_click)
        sl.addWidget(self.tier_prev)
        self.tier_del = make_btn(tr("Delete photo"), "ghost", tr("Removes this saved photo from the sidebar. "
                                                                  "Open the tier list to save a new one."))
        self.tier_del.clicked.connect(self.delete_tier_photo)
        sl.addWidget(self.tier_del)

        sl.addStretch(1)
        reset = make_btn(tr("Reset filters"), "ghost")
        reset.clicked.connect(self.reset_filters)
        sl.addWidget(reset)
        # language and backup: a single button with a menu (one row instead of six)
        self.lang_combo = make_combo()      # not visible: holds the chosen language and triggers the switch
        for code, label in LANGUAGES:
            self.lang_combo.addItem(label, code)
        self.lang_combo.setCurrentIndex(max(self.lang_combo.findData(LANG), 0))
        self.lang_combo.currentIndexChanged.connect(self.on_language_changed)
        self.opts_btn = make_btn(tr("⚙  Settings"), "ghost",
                                 tr("Language, theme, backups and updates"))
        self.opts_menu = QMenu(self)
        style_menu(self.opts_menu)
        lang_menu = self.opts_menu.addMenu(tr("Language"))
        style_menu(lang_menu)
        for i, (code, label) in enumerate(LANGUAGES):
            act = lang_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(code == LANG)
            act.triggered.connect(lambda _=False, i=i: self.lang_combo.setCurrentIndex(i))
        theme_menu = self.opts_menu.addMenu(tr("Theme"))
        style_menu(theme_menu)
        for code, label in THEME_NAMES:
            act = theme_menu.addAction(tr(label))
            act.setCheckable(True)
            act.setChecked(code == THEME)
            act.triggered.connect(lambda _=False, code=code: self.on_theme_changed(code))
        self.opts_menu.addSeparator()
        self.opts_menu.addAction(tr("Export backup…")).triggered.connect(self.export_backup)
        self.opts_menu.addAction(tr("Import backup…")).triggered.connect(self.import_backup)
        self.opts_menu.addSeparator()
        self.opts_menu.addAction(tr("Update the HowLongToBeat connection")).triggered.connect(self.update_connections)
        self.opts_menu.addSeparator()
        self.opts_menu.addAction(tr("Check for updates (version {v})…", v=APP_VERSION)).triggered.connect(self.check_updates)
        self.opts_btn.clicked.connect(self.show_opts_menu)
        sl.addWidget(self.opts_btn)

        # ---------- main area ----------
        mainw = QWidget()
        main = QVBoxLayout(mainw)
        main.setContentsMargins(26, 24, 26, 12)
        main.setSpacing(14)
        top = QHBoxLayout()
        top.setSpacing(12)
        self.side_btn = make_toggle_btn(_icon_sidebar, tr("Show or hide the sidebar (Ctrl+B)"))
        self.side_btn.setChecked(not self.config.get("sidebar_hidden"))
        self.side_btn.clicked.connect(self.toggle_sidebar)
        top.addWidget(self.side_btn)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search game…   (Ctrl+F)"))
        self.search.addAction(search_icon(), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(lambda _t: self._refresh_timer.start())
        top.addWidget(self.search, 1)
        self.btn_cards = make_toggle_btn(_icon_grid, tr("Card view"))
        self.btn_list = make_toggle_btn(_icon_list, tr("List view with thumbnails and details"))
        self.btn_cards.clicked.connect(lambda _=False: self.set_view("cards"))
        self.btn_list.clicked.connect(lambda _=False: self.set_view("list"))
        top.addWidget(self.btn_cards)
        top.addWidget(self.btn_list)
        self.year_combo = make_combo()
        self.year_combo.setMinimumWidth(110)
        self.year_combo.currentIndexChanged.connect(self.on_year_changed)
        top.addWidget(self.year_combo)
        # new list / delete list: in a small menu, so the destructive "delete" is not a big red button
        # next to the ones you use every day
        self.year_btn = make_btn("⋯", "ghost", tr("List options: new list for another year, delete this list"))
        self.year_btn.setFixedWidth(42)
        self.year_btn.setStyleSheet("padding: 0px; font-size: 18px;")
        self.year_btn.clicked.connect(self.show_year_menu)
        top.addWidget(self.year_btn)
        self.tier_btn = tier = make_btn("Tier list", "soft", tr("Open the tier list of this list"))
        tier.clicked.connect(self.open_tierlist)
        top.addWidget(tier)
        self.add_btn = add = make_btn(tr("+  Add game"), "primary")
        add.clicked.connect(self.add_game)
        top.addWidget(add)
        main.addLayout(top)
        # Second row of the top bar: only used when the window is narrow (see layout_topbar)
        self.mainw = mainw
        self.top_row1 = top
        self.top_row2 = QHBoxLayout()
        self.top_row2.setContentsMargins(0, 0, 0, 0)
        self.top_row2.setSpacing(8)
        self.top_row2_w = QWidget()
        self.top_row2_w.setLayout(self.top_row2)
        self.top_row2_w.setVisible(False)
        main.addWidget(self.top_row2_w)
        self._top_wide = True
        self._top_pending = False
        mainw.installEventFilter(self)

        self.stack = QStackedWidget()
        self.list = QListWidget()
        # several games at once: Ctrl + click adds / removes one, Shift + click a range, Ctrl + A all
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.itemSelectionChanged.connect(self.update_selection_info)
        self.list.setMouseTracking(True)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.delegate = CardDelegate(self.list)
        self.row_delegate = RowDelegate(self.list)
        self.delegate.zoom = self.row_delegate.zoom = self.game_zoom
        self.apply_view_mode()
        self.list.viewport().installEventFilter(self)   # to readjust the rows when the width changes
        self.list.itemDoubleClicked.connect(lambda it: self.edit_game(it.data(ROLE_ID)))
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.context_menu)
        self.stack.addWidget(self.list)
        self.empty = QLabel("")
        self.empty.setObjectName("empty")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.empty)
        main.addWidget(self.stack, 1)

        self.notice_bar = self.build_notice_bar()
        main.addWidget(self.notice_bar)

        self.stats = QLabel("")
        self.stats.setObjectName("stats")
        main.addWidget(self.stats)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(6)
        self.splitter.setChildrenCollapsible(True)
        self.splitter.addWidget(side)
        self.splitter.addWidget(mainw)
        self.splitter.setCollapsible(0, True)
        self.splitter.setCollapsible(1, False)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([self._side_w, 1280 - self._side_w])
        self.splitter.splitterMoved.connect(self.on_splitter_moved)
        root.addWidget(self.splitter, 1)
        self._cfg_timer = QTimer(self)
        self._cfg_timer.setSingleShot(True)
        self._cfg_timer.setInterval(400)
        self._cfg_timer.timeout.connect(self.save_config)

        QShortcut(QKeySequence("Ctrl+N"), self).activated.connect(self.add_game)
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self.search.setFocus)
        QShortcut(QKeySequence("Ctrl+B"), self).activated.connect(self.toggle_sidebar)
        del_sc = QShortcut(QKeySequence("Delete"), self.list)
        del_sc.setContext(Qt.ShortcutContext.WidgetShortcut)   # only when the list has focus (not when deleting text in the search box)
        del_sc.activated.connect(self.delete_selected)
        QShortcut(QKeySequence("Ctrl+Z"), self).activated.connect(self.undo_last)
        esc = QShortcut(QKeySequence("Escape"), self.list)
        esc.setContext(Qt.ShortcutContext.WidgetShortcut)
        esc.activated.connect(self.list.clearSelection)
        # with the list focused: Enter / F2 = edit the selected game, 1-5 = change its status
        list_keys = [("Return", self.edit_selected), ("Enter", self.edit_selected), ("F2", self.edit_selected)]
        list_keys += [(str(n), functools.partial(self.status_selected, s)) for n, s in enumerate(STATUSES, 1)]
        for key, fn in list_keys:
            sc = QShortcut(QKeySequence(key), self.list)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(fn)

        self.restore_filters()
        self.fill_years()
        self.refresh()
        QTimer.singleShot(0, self._init_sidebar)
        QTimer.singleShot(0, self.layout_topbar)
        if self._load_problem:
            QTimer.singleShot(0, self.warn_load_problem)

    def warn_load_problem(self):
        bad, snap = self._load_problem
        self._load_problem = None
        if snap:
            text = tr("Your game list (games.json) could not be read, so the automatic copy from {date} was "
                      "loaded ({n} games).\n\nThe damaged file was kept here, in case you need it:\n{path}",
                      date=snap.stem.replace("games_", ""), n=len(self.games), path=bad)
        else:
            text = tr("Your game list (games.json) could not be read and there is no automatic copy to "
                      "recover it from. You can import a backup from ⚙.\n\nThe damaged file was kept here:\n{path}",
                      path=bad)
        QMessageBox.warning(self, tr("Problem reading your list"), text)

    # ---- sidebar: width, hide, and tier list preview ----
    def _init_sidebar(self):
        """Once the window is on screen: apply the saved width (or leave it hidden)."""
        total = max(self.splitter.width(), 600)
        if self.config.get("sidebar_hidden"):
            self.splitter.setSizes([0, total])
            self.side_btn.setChecked(False)
        else:
            self.splitter.setSizes([self._side_w, max(1, total - self._side_w)])
            self.side_btn.setChecked(True)

    def on_splitter_moved(self, *_):
        w = self.splitter.sizes()[0]
        if w > 0:
            self._side_w = w
        self.config["sidebar_w"] = self._side_w
        self.config["sidebar_hidden"] = (w == 0)
        self.side_btn.setChecked(w > 0)
        self._cfg_timer.start()

    def toggle_sidebar(self, *_):
        sizes = self.splitter.sizes()
        total = sum(sizes)
        if sizes[0] > 0:
            self._side_w = sizes[0]
            self.splitter.setSizes([0, total])
        else:
            w = min(max(self._side_w, 210), 520)
            self.splitter.setSizes([w, max(1, total - w)])
        self.on_splitter_moved()

    def tier_photo_path(self):
        return TIER_PHOTOS / f"tierlist_{self.cur_year}.png"

    def update_tier_preview(self):
        """Show in the sidebar the photo of the saved tier list of the current list (year)."""
        self.tier_title.setText(tr("Tier list {year}", year=self.cur_year))
        path = self.tier_photo_path()
        try:
            stamp = (self.cur_year, path.stat().st_mtime_ns)
        except OSError:
            stamp = (self.cur_year, None)
        if stamp == self._tier_stamp:
            return   # nothing changed: do not read the image again
        self._tier_stamp = stamp
        pm = QPixmap(str(path)) if stamp[1] is not None else QPixmap()
        self.tier_del.setVisible(not pm.isNull())   # the delete button only shows when there is a photo
        if pm.isNull():
            self.tier_prev.set_empty(tr("There is no saved tier list for {year} yet.\n"
                                       "Click to open it: it is saved when you close it.", year=self.cur_year))
        else:
            self.tier_prev.set_photo(pm)

    def delete_tier_photo(self, *_):
        """Remove this year's saved photo from the sidebar. The tier list is kept:
        opening and closing it saves a new photo and it shows up again."""
        path = self.tier_photo_path()
        if not confirm_box(self, tr("Delete photo"),
                           tr("Delete the saved photo of the {year} tier list?\n"
                              "The tier list itself is kept: open it to save a new photo.", year=self.cur_year),
                           tr("Delete")):
            return
        try:
            path.unlink()
        except OSError:
            pass
        self._tier_stamp = None
        self.update_tier_preview()

    def on_tier_click(self):
        path = self.tier_photo_path()
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            self.open_tierlist()

    # ---- view: cards or list ----
    def apply_view_mode(self):
        lst = self.list
        if self.view_mode == "list":
            lst.setViewMode(QListView.ViewMode.ListMode)
            lst.setFlow(QListView.Flow.TopToBottom)
            lst.setWrapping(False)
            lst.setGridSize(QSize())
            lst.setUniformItemSizes(False)
            lst.setSpacing(0)
            lst.setItemDelegate(self.row_delegate)
        else:
            lst.setViewMode(QListView.ViewMode.IconMode)
            lst.setFlow(QListView.Flow.LeftToRight)
            lst.setWrapping(True)
            lst.setResizeMode(QListView.ResizeMode.Adjust)
            lst.setMovement(QListView.Movement.Static)
            lst.setUniformItemSizes(True)
            self.set_card_grid(*self.card_grid())
            lst.setGridSize(QSize(self.delegate.cell_w, self.card_cell_h()))
            lst.setItemDelegate(self.delegate)
        self.btn_cards.setChecked(self.view_mode == "cards")
        self.btn_list.setChecked(self.view_mode == "list")

    CARD_MIN_SCALE, CARD_MAX_SCALE = 0.88, 1.2   # how much the cards may shrink / grow to fill the row

    def card_grid(self):
        """(cell width, zoom of the cards). The cards adapt by themselves to the width of the window: the
        gap between them is always the same and the cards shrink (down to 88 %) or grow (up to 120 %) so the
        row is filled. They shrink only if that way one more column fits, which helps on small screens."""
        base = CARD_W * self.game_zoom
        # the same width Qt uses to wrap the grid: the whole area minus the scroll bar's room (always reserved)
        lst = self.list
        bar = lst.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent, None, lst.verticalScrollBar())
        avail = lst.maximumViewportSize().width() - bar - 2
        cols = max(1, int(avail // base))
        if avail // (cols + 1) >= math.ceil(base * self.CARD_MIN_SCALE):   # whole pixels (no rounding below the minimum)
            cols += 1   # slightly smaller cards, one more column
        cell = int(avail // cols)
        scale = max(self.CARD_MIN_SCALE, min(cell / base, self.CARD_MAX_SCALE))
        if cell < base * scale:   # a very narrow window: one column, as wide as there is room for
            cell = int(base * scale)
        return cell, self.game_zoom * scale

    def set_card_grid(self, cell, scale):
        self.delegate.cell_w = cell
        self.delegate.card_px = min(cell, round(CARD_W * self.game_zoom * scale))
        self.delegate.zoom = self.delegate.card_px / CARD_W

    def card_cell_h(self):
        return self.delegate.card_h() + 2

    def update_card_grid(self):
        if self.view_mode != "cards":
            return
        w, z = self.card_grid()
        old = (self.delegate.cell_w, self.delegate.card_px)
        self.set_card_grid(w, z)
        if (self.delegate.cell_w, self.delegate.card_px) == old:
            return
        h = self.card_cell_h()
        self.list.setGridSize(QSize(w, h))
        for i in range(self.list.count()):
            self.list.item(i).setSizeHint(QSize(w, h))
        self.list.doItemsLayout()

    def set_view(self, mode):
        if mode != self.view_mode:
            self.view_mode = mode
            self.config["view"] = mode
            self.apply_view_mode()
            self.save_config()
            self.refresh()
        else:
            self.btn_cards.setChecked(mode == "cards")
            self.btn_list.setChecked(mode == "list")

    def eventFilter(self, obj, e):
        if obj is self.mainw and e.type() == QEvent.Type.Resize and not self._top_pending:
            self._top_pending = True
            QTimer.singleShot(0, self.layout_topbar)
        if (self.view_mode == "list" and e.type() == QEvent.Type.Resize
                and obj is self.list.viewport()):
            QTimer.singleShot(0, self.list.doItemsLayout)   # rows take the full width
        if (self.view_mode == "cards" and e.type() == QEvent.Type.Resize
                and obj is self.list.viewport()):
            QTimer.singleShot(0, self.update_card_grid)   # the cards spread out over the full width
        return super().eventFilter(obj, e)

    def layout_topbar(self):
        """One row when there is room; two rows when the window is narrow, so no button gets squashed.
        The main area also reserves the width it needs: when space runs out, the sidebar shrinks instead."""
        self._top_pending = False
        top_gap, low_gap, search_want, search_min = 12, 8, 220, 120
        row1_low = [self.side_btn, self.btn_cards, self.btn_list]
        row2_low = [self.year_combo, self.year_btn, self.tier_btn, self.add_btn]
        all_fixed = row1_low + row2_low

        def hints(ws):
            total = 0
            for w in ws:
                w.ensurePolished()
                total += max(w.sizeHint().width(), w.minimumSizeHint().width())
            return total

        margins = 52   # 26 + 26 of the main area
        need_one_row = hints(all_fixed) + top_gap * len(all_fixed) + search_want
        need_row1 = hints(row1_low) + low_gap * len(row1_low) + search_min
        need_row2 = hints(row2_low) + low_gap * (len(row2_low) - 1)
        self.mainw.setMinimumWidth(max(need_row1, need_row2) + margins)

        wide = (self.mainw.width() - margins) >= need_one_row
        if wide == self._top_wide:
            return
        self._top_wide = wide
        for lay in (self.top_row1, self.top_row2):
            while lay.count():
                lay.takeAt(0)
        if wide:
            self.top_row1.setSpacing(top_gap)
            self.top_row1.addWidget(self.side_btn)
            self.top_row1.addWidget(self.search, 1)
            for w in row1_low[1:] + row2_low:
                self.top_row1.addWidget(w)
            self.top_row2_w.setVisible(False)
        else:
            self.top_row1.setSpacing(low_gap)
            self.top_row1.addWidget(self.side_btn)
            self.top_row1.addWidget(self.search, 1)
            for w in row1_low[1:]:
                self.top_row1.addWidget(w)
            for w in row2_low[:-1]:
                self.top_row2.addWidget(w)
            self.top_row2.addStretch(1)
            self.top_row2.addWidget(self.add_btn)
            self.top_row2_w.setVisible(True)

    def closeEvent(self, e):
        self.finish_undo()   # a pending deletion becomes final
        if getattr(self, "_switching", False):   # the new window already took over the settings
            super().closeEvent(e)
            return
        try:
            self.config["geometry"] = bytes(self.saveGeometry()).hex()
            self.config["filters"] = self.filters_state()
            self.save_config()
        except Exception:
            pass
        super().closeEvent(e)

    # ---- filters and sorting: saved on close and restored on open ----
    def filters_state(self):
        return {
            "statuses": {s: c.isChecked() for s, c in self.status_checks.items()},
            "platform": self.plat_combo.currentData() or "",
            "platinum_only": self.plat_only.isChecked(),
            "rerun_only": self.rerun_only.isChecked(),
            "sort": SORT_OPTIONS[self.sort_combo.currentIndex()][0],
            "sort_desc": self.sort_desc,
            "min_h": self.min_h.value(),
            "max_h": self.max_h.value(),
        }

    def restore_filters(self):
        f = self.config.get("filters")
        if not isinstance(f, dict):
            return
        widgets = list(self.status_checks.values()) + [self.min_h, self.max_h, self.plat_combo,
                                                        self.plat_only, self.rerun_only, self.sort_combo]
        for w in widgets:
            w.blockSignals(True)
        try:
            st = f.get("statuses")
            if isinstance(st, dict) and any(st.get(s, True) for s in self.status_checks):
                for s, c in self.status_checks.items():
                    c.setChecked(bool(st.get(s, True)))
            self.plat_combo.setCurrentIndex(max(self.plat_combo.findData(f.get("platform") or ""), 0))
            self.plat_only.setChecked(bool(f.get("platinum_only")))
            self.rerun_only.setChecked(bool(f.get("rerun_only")))
            names = [n for n, _ in SORT_OPTIONS]
            if f.get("sort") in names:
                self.sort_combo.setCurrentIndex(names.index(f["sort"]))
            self.sort_desc = bool(f.get("sort_desc", True))
            self.update_dir_btn()
            for fld, key in ((self.min_h, "min_h"), (self.max_h, "max_h")):
                try:
                    fld.setValue(float(f.get(key) or 0))
                except (TypeError, ValueError):
                    pass
        finally:
            for w in widgets:
                w.blockSignals(False)

    # ---- backup ----
    def export_backup(self, *_):
        default = str(Path.home() / f"backlog_backup_{time.strftime('%Y-%m-%d')}.zip")
        path, _f = QFileDialog.getSaveFileName(self, tr("Export backup"), default, tr("Backup (*.zip)"))
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"
        try:
            write_backup(path, self.games, self.config)
        except Exception as e:
            QMessageBox.warning(self, tr("Could not export"), f"{type(e).__name__}: {e}")
            return
        QMessageBox.information(self, tr("Backup created"),
                                tr("Backup saved to:\n{path}\n\n{n} games with their covers and tier lists.",
                                   path=path, n=len(self.games)))

    def import_backup(self, *_):
        path, _f = QFileDialog.getOpenFileName(self, tr("Import backup"), str(Path.home()),
                                               tr("Backup (*.zip)"))
        if not path:
            return
        try:
            with zipfile.ZipFile(path) as z:
                check_backup(z)
                raw = read_json_member(z, "games.json", [])
                if not isinstance(raw, list):
                    raise ValueError(tr("The backup's game list is not valid."))
                games = [sanitize_imported(g) for g in raw if isinstance(g, dict)]
                have = {g["id"] for g in self.games}
                n_new = sum(1 for g in games if g["id"] not in have)
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Question)
                box.setWindowTitle(tr("Import a backup"))
                box.setText(tr("The backup has {n} games, {new} of them that you don't have now.\n\n"
                               "Replace: your list becomes the backup's (a backup of yours is saved first).\n"
                               "Add: only the games you are missing are added and nothing of yours is touched.",
                               n=len(games), new=n_new))
                b_rep = box.addButton(tr("Replace my data"), QMessageBox.ButtonRole.DestructiveRole)
                b_rep.setObjectName("danger")
                b_add = box.addButton(tr("Add what is missing"), QMessageBox.ButtonRole.AcceptRole)
                b_add.setObjectName("soft")
                b_no = box.addButton(tr("Cancel"), QMessageBox.ButtonRole.RejectRole)
                b_no.setObjectName("ghost")
                box.setDefaultButton(b_no)
                box.exec()
                clicked = box.clickedButton()
                if clicked is b_rep:
                    msg = self._import_replace(z, games)
                elif clicked is b_add:
                    msg = self._import_merge(z, games)
                else:
                    return
        except (zipfile.BadZipFile, ValueError, KeyError, OSError) as e:
            QMessageBox.warning(self, tr("Could not import"), str(e) or type(e).__name__)
            return
        self._reload_after_import()
        QMessageBox.information(self, tr("Backup imported"), msg)

    def _import_replace(self, z, games):
        safety_dir = DATA_DIR / "backups"
        safety_dir.mkdir(parents=True, exist_ok=True)
        safety = safety_dir / f"before_import_{time.strftime('%Y%m%d_%H%M%S')}.zip"
        write_backup(safety, self.games, self.config)
        for d in BACKUP_DIRS:
            folder = DATA_DIR / d
            if folder.is_dir():
                for f in folder.iterdir():
                    if f.is_file():
                        try:
                            f.unlink()
                        except OSError:
                            pass
        for name in z.namelist():
            pp = PurePosixPath(name)
            if len(pp.parts) == 2 and pp.parts[0] in BACKUP_DIRS:
                extract_member(z, name)
        tiers = read_json_member(z, "tierlists.json", {})
        save_json(GAMES_FILE, games)
        save_json(TIER_FILE, tiers if isinstance(tiers, dict) else {})
        cfg_in = read_json_member(z, "config.json", {})
        if isinstance(cfg_in, dict):
            years = [y for y in cfg_in.get("years", []) if isinstance(y, int) and not isinstance(y, bool)]
            if years:
                self.config["years"] = years
            if isinstance(cfg_in.get("last_year"), int):
                self.config["last_year"] = cfg_in["last_year"]
            if cfg_in.get("view") in ("cards", "list"):
                self.config["view"] = cfg_in["view"]
        self.games = games
        return tr("Your list now has {n} games.\n\nBefore replacing, a copy of the previous data was saved to:\n{path}",
                  n=len(games), path=safety)

    def _import_merge(self, z, games):
        have = {g["id"] for g in self.games}
        names = set(z.namelist())
        added = 0
        for g in games:
            if g["id"] in have:
                continue
            cov = g.get("cover")
            if cov and f"covers/{cov}" in names and not (COVERS_DIR / cov).exists():
                extract_member(z, f"covers/{cov}")
            self.games.append(g)
            have.add(g["id"])
            added += 1
        tiers = read_json_member(z, "tierlists.json", {})
        local = load_json(TIER_FILE, {})
        if isinstance(tiers, dict):
            for y, data in tiers.items():
                if y not in local and isinstance(data, dict):   # tier lists you already have are left untouched
                    local[y] = data
                    photo = f"tierlists/tierlist_{y}.png"
                    if photo in names and not (TIER_PHOTOS / f"tierlist_{y}.png").exists():
                        extract_member(z, photo)
        save_json(GAMES_FILE, self.games)
        save_json(TIER_FILE, local)
        return (tr("{n} new games were added.", n=added) if added
                else tr("No game was missing: everything was already in your list."))

    def _reload_after_import(self):
        self.hide_notice()
        self.delegate._cache.clear()
        self.row_delegate._cache.clear()
        _TIER_PIX.clear()
        self._tier_stamp = None
        base = set(self.config.get("years", [])) or {time.localtime().tm_year}
        self.years = sorted({g["year"] for g in self.games} | base)
        last = self.config.get("last_year")
        self.cur_year = last if last in self.years else self.years[-1]
        self.fill_years()
        self.save_config()
        self.refresh()

    # ---- lists by year ----
    def fill_years(self):
        self.year_combo.blockSignals(True)
        self.year_combo.clear()
        for y in self.years:
            self.year_combo.addItem(tr("List {year}", year=y), y)
        self.year_combo.setCurrentIndex(max(self.year_combo.findData(self.cur_year), 0))
        self.year_combo.blockSignals(False)

    def save_config(self):
        self.config["years"] = self.years
        self.config["last_year"] = self.cur_year
        save_json(CONFIG_FILE, self.config)

    def year_games(self):
        return [g for g in self.games if g.get("year") == self.cur_year]

    def on_year_changed(self, *_):
        y = self.year_combo.currentData()
        if y:
            self.cur_year = y
            self.save_config()
            self.refresh()

    def set_year(self, y):
        if y not in self.years:
            self.years = sorted(set(self.years) | {y})
        self.cur_year = y
        self.fill_years()
        self.save_config()
        self.refresh()

    def add_year(self, *_):
        text, ok = QInputDialog.getText(self, tr("New list"), tr("List year (for example 2027):"),
                                        text=str(self.cur_year + 1))
        if not ok:
            return
        try:
            y = int(text.strip())
        except ValueError:
            y = 0
        if not 1980 <= y <= 2100:
            QMessageBox.warning(self, tr("Invalid year"), tr("Enter a year between 1980 and 2100."))
            return
        self.set_year(y)

    def delete_year(self, *_):
        y = self.cur_year
        yg = self.year_games()
        txt = tr("Delete the {year} list?", year=y)
        if yg:
            txt += tr("\nIts {n} games, covers and tier list will be deleted. This cannot be undone.", n=len(yg))
        if not confirm_box(self, tr("Delete list"), txt, tr("Yes, delete")):
            return
        self.hide_notice()
        for g in yg:
            if g.get("cover"):
                try:
                    (COVERS_DIR / g["cover"]).unlink()
                except OSError:
                    pass
        self.games = [g for g in self.games if g.get("year") != y]
        save_json(GAMES_FILE, self.games)
        data = load_json(TIER_FILE, {})
        if data.pop(str(y), None) is not None:
            save_json(TIER_FILE, data)
        try:
            (TIER_PHOTOS / f"tierlist_{y}.png").unlink()
        except OSError:
            pass
        self.years = [v for v in self.years if v != y] or [time.localtime().tm_year]
        self.cur_year = next((v for v in reversed(self.years) if v < y), self.years[0])   # the closest previous list
        self.fill_years()
        self.save_config()
        self.refresh()

    def open_tierlist(self, *_):
        yg = self.year_games()
        if not yg:
            QMessageBox.information(self, "Tier list", tr("The {year} list has no games yet.", year=self.cur_year))
            return
        # games in "Planeado" (planned) have not been played yet: they are not part of the tier list
        ranked = [g for g in yg if g.get("status") != "Planeado"]
        if not ranked:
            QMessageBox.information(self, "Tier list", tr("The {year} list has no games to rank yet "
                                                          "(Planned games are not included in the tier list).",
                                                          year=self.cur_year))
            return
        TierListDialog(self, self.cur_year, ranked).exec()
        self.update_tier_preview()   # when it closes, the photo is saved: it shows up in the sidebar right away

    # ---- UI utilities ----
    def on_theme_changed(self, code):
        """Switch theme: the colors are applied and a fresh window opens (like when the language changes)."""
        if code == THEME:
            return
        self.config["theme"] = code
        self.config["geometry"] = bytes(self.saveGeometry()).hex()
        self.config["filters"] = self.filters_state()
        self.save_config()
        apply_theme(QApplication.instance(), code)
        self._switching = True
        new = MainWindow()
        _WINDOWS.append(new)
        new.show()
        self.close()

    def on_language_changed(self, *_):
        """Switch language: save the window state and open a fresh window in the new language."""
        code = self.lang_combo.currentData()
        if not code or code == LANG:
            return
        self.config["lang"] = code
        self.config["geometry"] = bytes(self.saveGeometry()).hex()
        self.config["filters"] = self.filters_state()
        self.save_config()
        set_language(code)
        self._switching = True
        new = MainWindow()
        _WINDOWS.append(new)
        new.show()
        self.close()

    def show_year_menu(self, *_):
        m = QMenu(self)
        style_menu(m)
        m.addAction(tr("+ New list for another year…")).triggered.connect(self.add_year)
        m.addAction(tr("Move or copy games to another list…")).triggered.connect(self.transfer_games)
        m.addSeparator()
        m.addAction(tr("Delete the {year} list…", year=self.cur_year)).triggered.connect(self.delete_year)
        m.exec(self.year_btn.mapToGlobal(self.year_btn.rect().bottomLeft()))

    def show_opts_menu(self, *_):
        pos = self.opts_btn.mapToGlobal(self.opts_btn.rect().topLeft())
        pos.setY(pos.y() - self.opts_menu.sizeHint().height() - 4)   # the button is at the bottom: the menu opens upwards
        self.opts_menu.exec(pos)

    def section(self, text):
        l = QLabel(tr(text))
        l.setObjectName("section")
        return l

    def update_dir_btn(self):
        self.dir_btn.setText(tr("↓  Highest first") if self.sort_desc else tr("↑  Lowest first"))

    def toggle_dir(self):
        self.sort_desc = not self.sort_desc
        self.update_dir_btn()
        self.refresh()

    def reset_filters(self):
        self._refresh_timer.stop()
        widgets = list(self.status_checks.values()) + [self.min_h, self.max_h, self.plat_combo, self.plat_only, self.rerun_only]
        for w in widgets:
            w.blockSignals(True)
        for c in self.status_checks.values():
            c.setChecked(True)
        self.min_h.setValue(0)
        self.max_h.setValue(0)
        self.plat_combo.setCurrentIndex(0)
        self.plat_only.setChecked(False)
        self.rerun_only.setChecked(False)
        for w in widgets:
            w.blockSignals(False)
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.sort_combo.blockSignals(True)
        self.sort_combo.setCurrentIndex(0)
        self.sort_combo.blockSignals(False)
        self.sort_desc = True
        self.update_dir_btn()
        self.refresh()

    # ---- filtering and sorting ----
    def visible_games(self):
        # controls are read ONCE, not once per game
        allowed = {s for s, c in self.status_checks.items() if c.isChecked()}
        plat = self.plat_combo.currentData() or ""
        only_plat = self.plat_only.isChecked()
        only_rerun = self.rerun_only.isChecked()
        q = _fold(self.search.text())
        lo, hi = self.min_h.value(), self.max_h.value()

        games = []
        for g in self.year_games():
            if g["status"] not in allowed:
                continue
            if plat and g.get("platform") != plat:
                continue
            if only_plat and not g.get("platinum"):
                continue
            if only_rerun and not g.get("rerun"):
                continue
            if q and not any(q in _fold(t) for t in (g["name"], g.get("notes"), plat_label(g.get("platform") or ""),
                                                      plat_short(g.get("platform") or ""))):
                continue   # the search also looks in the notes and the platform
            h = g.get("hours")
            if lo > 0 and (h is None or h < lo):
                continue
            if hi > 0 and (h is None or h > hi):
                continue
            games.append(g)

        key = SORT_OPTIONS[self.sort_combo.currentIndex()][1]
        keyed = [(key(g), g) for g in games]
        with_v = [kg for kg in keyed if kg[0] is not None]
        without = [kg[1] for kg in keyed if kg[0] is None]
        with_v.sort(key=lambda kg: kg[0], reverse=self.sort_desc)
        return [kg[1] for kg in with_v] + without  # games with no data always go last

    def refresh(self, *_):
        selected = self.current_id()
        sel_ids = set(self.selected_ids())
        shown = self.visible_games()
        self.delegate.games = {g["id"]: g for g in shown}
        self.row_delegate.games = self.delegate.games
        self.list.setUpdatesEnabled(False)
        self.list.clear()
        for g in shown:
            it = QListWidgetItem()
            it.setData(ROLE_ID, g["id"])
            if self.view_mode == "cards":
                it.setSizeHint(QSize(self.delegate.cell_w or round(CARD_W * self.game_zoom), self.card_cell_h()))
            # the hover shows the game's notes and, if there is one, the Metacritic warning (nothing = no tooltip)
            tip = [g["notes"]] if g.get("notes") else []
            if g.get("meta_other") and g.get("meta_score") is not None:
                tip.append(meta_other_text(g))
            if tip:
                it.setToolTip("\n\n".join(tip))
            self.list.addItem(it)
            if g["id"] == selected:
                self.list.setCurrentItem(it)
            if g["id"] in sel_ids:
                it.setSelected(True)
        self.list.setUpdatesEnabled(True)
        yg = self.year_games()
        if not yg:
            self.empty.setText(tr("This list has no games yet.\nPress  + Add game  and type the name:\ncover, score and hours fill in on their own."))
            self.stack.setCurrentWidget(self.empty)
        elif not shown:
            self.empty.setText(tr("No game matches the current filters."))
            self.stack.setCurrentWidget(self.empty)
        else:
            self.stack.setCurrentWidget(self.list)
        for s, c in self.status_checks.items():   # how many games of the list have each status
            c.setText(f"{status_label(s)}  ({sum(1 for g in yg if g['status'] == s)})")
        done = sum(1 for g in yg if g["status"] == "Completado")
        total_h = sum(g["hours"] for g in yg if g.get("hours") and g["status"] in ("Planeado", "Jugando", "Pausado"))
        plats = sum(1 for g in yg if g.get("platinum"))
        self.stats.setText(tr(
            "List {year}  ·  {shown} of {total} games  ·  {done} completed  ·  🏆 {plats} platinums  ·  "
            "{hours} h of pending backlog (planned, playing and paused)",
            year=self.cur_year, shown=len(shown), total=len(yg), done=done, plats=plats, hours=f"{total_h:g}"))
        self._stats_text = self.stats.text()
        self.update_selection_info()
        self.update_tier_preview()

    def selected_ids(self):
        """Ids of the selected games, in the order they are shown."""
        return [self.list.item(i).data(ROLE_ID) for i in range(self.list.count()) if self.list.item(i).isSelected()]

    def update_selection_info(self):
        """When several games are selected, the bottom line says how many and what you can do with them."""
        base = getattr(self, "_stats_text", self.stats.text())
        n = len(self.selected_ids())
        if n > 1:
            base += "  ·  " + tr("{n} selected (right-click to act on all of them, Esc to unselect)", n=n)
        self.stats.setText(base)

    # ---- actions ----
    def current_id(self):
        it = self.list.currentItem()
        return it.data(ROLE_ID) if it else None

    def find(self, gid):
        return next((g for g in self.games if g["id"] == gid), None)

    def persist(self):
        save_json(GAMES_FILE, self.games)
        self.refresh()   # the cover cache does not need clearing: every new cover has a new file name

    def add_game(self, *_):
        dlg = GameDialog(self, None, self.config, self.years, self.cur_year, existing=self.games)
        if not dlg.exec():
            return
        g = None
        try:
            g = dlg.result_game()
            self.games.append(g)
            if g["year"] != self.cur_year:
                self.set_year(g["year"])
            self.persist()
        except Exception as e:
            # report the failure (and log it) instead of failing silently
            sys.excepthook(*sys.exc_info())
            QMessageBox.warning(self, tr("Could not add the game"),
                                tr("Something went wrong while adding “{name}”: {err}\n\nThe details are in error.log, "
                                   "inside the folder {folder}",
                                   name=dlg.name.text().strip(), err=f"{type(e).__name__}: {e}", folder=str(DATA_DIR)))
            return
        # if a filter or the search box hides it (for example Planned unchecked), they are cleared so you can see it
        if not any(x["id"] == g["id"] for x in self.visible_games()):
            self.search.clear()
            self.reset_filters()
        self.select_game(g["id"])

    def select_game(self, gid):
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(ROLE_ID) == gid:
                self.list.setCurrentItem(it)
                self.list.scrollToItem(it)
                break

    def edit_game(self, gid):
        g = self.find(gid)
        if not g:
            return
        dlg = GameDialog(self, g, self.config, self.years, self.cur_year, existing=self.games)
        if dlg.exec():
            new = dlg.result_game()
            self.games[self.games.index(g)] = new
            self.persist()
            if new["year"] != self.cur_year:
                self.show_notice(tr("“{name}” moved to the {year} list.", name=new["name"], year=new["year"]))
            else:
                self.select_game(gid)

    def set_status(self, gid, status):
        g = self.find(gid)
        if g:
            g["status"] = status
            self.persist()
            self.select_game(gid)

    def toggle_flag(self, gid, key):
        """Platinum / Rerun on and off straight from the context menu."""
        g = self.find(gid)
        if g:
            g[key] = not g.get(key)
            self.persist()
            self.select_game(gid)

    def move_to_year(self, gid, year):
        g = self.find(gid)
        if g and g.get("year") != year:
            g["year"] = year
            self.persist()
            self.show_notice(tr("“{name}” moved to the {year} list.", name=g["name"], year=year))

    def delete_game(self, gid):
        self.delete_games([gid])

    def delete_games(self, gids):
        """Deleted at once, with an "Undo" bar for a few seconds (the cover files are only removed after that)."""
        gone = [g for g in self.games if g["id"] in set(gids)]
        if not gone:
            return
        self.finish_undo()   # the previous action can no longer be undone
        before = list(self.games)
        self.games = [g for g in self.games if g["id"] not in set(gids)]

        def restore():
            self.games = before
            years = {g.get("year") for g in gone}
            if self.cur_year not in years:
                self.set_year(gone[0]["year"])
            self.persist()
            self.select_games([g["id"] for g in gone])

        def final():   # the deletion becomes final: remove the cover files (unless another game uses them)
            for g in gone:
                cov = g.get("cover")
                if cov and not any(x.get("cover") == cov for x in self.games):
                    try:
                        (COVERS_DIR / cov).unlink()
                    except OSError:
                        pass

        self._undo = {"restore": restore, "final": final}
        self.persist()
        msg = (tr("“{name}” deleted.", name=gone[0]["name"]) if len(gone) == 1
               else tr("Games deleted: {n}", n=len(gone)))
        self.show_notice(msg, undo=True)

    def select_games(self, gids):
        gids = set(gids)
        self.list.clearSelection()
        first = None
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(ROLE_ID) in gids:
                it.setSelected(True)
                first = first or it
        if first:
            self.list.scrollToItem(first)

    def set_status_many(self, gids, status):
        for gid in gids:
            g = self.find(gid)
            if g:
                g["status"] = status
        self.persist()

    def transfer_selected(self, gids):
        """Move or copy the games you selected by hand to another list."""
        chosen = [g for g in self.games if g["id"] in set(gids)]
        if not chosen:
            return
        dlg = TransferDialog(self, self.cur_year, self.year_games(), self.years, self.games, preset=chosen)
        if dlg.exec():
            self.do_transfer(*dlg.result_values())

    def undo_last(self, *_):
        """Undo the last deletion or the last move / copy of several games (while its bar is visible)."""
        if not self._undo:
            return
        u, self._undo = self._undo, None
        self.hide_notice()
        u["restore"]()

    def finish_undo(self):
        """The last action can no longer be undone (its bar closed)."""
        if not self._undo:
            return
        u, self._undo = self._undo, None
        if u.get("final"):
            u["final"]()

    # ---- move / copy several games to another list (for example the planned ones to next year) ----
    def transfer_games(self, *_):
        yg = self.year_games()
        if not yg:
            QMessageBox.information(self, tr("Move or copy games"),
                                    tr("The {year} list has no games yet.", year=self.cur_year))
            return
        dlg = TransferDialog(self, self.cur_year, yg, self.years, self.games)
        if not dlg.exec():
            return
        self.do_transfer(*dlg.result_values())

    def do_transfer(self, target, copy_mode, chosen):
        if not chosen:
            return
        self.finish_undo()
        have = {_fold(g["name"]) for g in self.games if g.get("year") == target}
        todo = [g for g in chosen if _fold(g["name"]) not in have]   # already in that list: left alone
        skipped = len(chosen) - len(todo)
        before = [dict(g) for g in self.games]
        new_covers = []
        for g in todo:
            if copy_mode:
                c = dict(g)
                c["id"] = uuid.uuid4().hex
                c["year"] = target
                c["added"] = time.time()
                if g.get("cover"):   # each copy gets its own cover file (deleting one never breaks the other)
                    fname = f"{c['id']}_{int(time.time())}{Path(g['cover']).suffix or '.jpg'}"
                    try:
                        shutil.copy2(COVERS_DIR / g["cover"], COVERS_DIR / fname)
                        c["cover"] = fname
                        new_covers.append(fname)
                    except OSError:
                        c["cover"] = ""
                self.games.append(c)
            else:
                g["year"] = target
        src_year = self.cur_year
        if target not in self.years:
            self.years = sorted(set(self.years) | {target})
            self.fill_years()
            self.save_config()
        self.persist()

        def restore():
            self.games = before
            for f in new_covers:
                try:
                    (COVERS_DIR / f).unlink()
                except OSError:
                    pass
            self.set_year(src_year)
            self.persist()

        self._undo = {"restore": restore}
        key = "Games copied to the {year} list: {n}" if copy_mode else "Games moved to the {year} list: {n}"
        msg = tr(key, n=len(todo), year=target)
        if skipped:
            msg += tr("  ·  already there, left as they were: {n}", n=skipped)
        self.show_notice(msg, undo=bool(todo))

    # ---- notice bar under the games (deleted / moved, with "Undo") ----
    def build_notice_bar(self):
        bar = QFrame()
        bar.setObjectName("noticeBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(14, 6, 8, 6)
        h.setSpacing(10)
        self.notice_lbl = QLabel("")
        h.addWidget(self.notice_lbl, 1)
        self.notice_undo = make_btn(tr("Undo"), "soft", "Ctrl+Z")
        self.notice_undo.clicked.connect(self.undo_last)
        h.addWidget(self.notice_undo)
        close = make_btn("✕", "ghost")
        close.setFixedWidth(38)
        close.setStyleSheet("padding: 0px;")
        close.clicked.connect(self.hide_notice)
        h.addWidget(close)
        bar.setVisible(False)
        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.setInterval(9000)
        self._notice_timer.timeout.connect(self.hide_notice)
        return bar

    def show_notice(self, text, undo=False):
        self.notice_lbl.setText(text)
        self.notice_undo.setVisible(undo)
        self.notice_bar.setVisible(True)
        self._notice_timer.start()

    def hide_notice(self, *_):
        self._notice_timer.stop()
        self.notice_bar.setVisible(False)
        self.finish_undo()

    # ---- background tasks: updating the HowLongToBeat connection and the app ----
    def on_task(self, msg):
        kind = msg[0]
        if kind == "app_check":
            self._updating = False
            self.hide_notice()
            result, info = msg[1]
            title = tr("Check for updates")
            if result == "error":
                QMessageBox.warning(self, title, tr("Could not check for updates ({err}). Check your internet "
                                                    "connection.", err=info))
            elif result == "none":
                QMessageBox.information(self, title, tr("No version of the app has been published yet."))
            elif result == "current":
                QMessageBox.information(self, title, tr("You have the latest version ({v}).", v=APP_VERSION))
            elif is_exe() and not info.get("exe"):
                QMessageBox.information(self, title, tr("Version {v} is published, but without the .exe yet. "
                                                        "Try again later.", v=info["version"]))
            elif self.ask_update(info):
                self.download_update(info)
        elif kind == "app_progress":
            _, done, total = msg
            pct = f"  {done * 100 // total} %" if total else f"  {done // (1024 * 1024)} MB"
            self.show_notice(tr("Downloading version {v}…", v=self._update_info["version"]) + pct)
            self._notice_timer.stop()
        elif kind == "app_ready":
            self._updating = False
            self.hide_notice()
            ok, payload = msg[1]
            title = tr("Check for updates")
            if ok:
                QMessageBox.information(self, title, tr("Version {v} is ready. The app will now close and open "
                                                        "again.", v=self._update_info["version"]))
                self.restart_into_update(payload)
                return
            reasons = {
                "onedir": tr("This copy of the app is a folder, not a single .exe, so it cannot update itself: "
                             "download the new version from GitHub."),
                "noexe": tr("The new version has no .exe attached."),
                "readonly": tr("The app cannot write in its own folder. Move it to a folder of yours (for example "
                               "Documents or the Desktop) and try again."),
                "corrupt": tr("The download arrived incomplete or damaged, so nothing was changed. Try again."),
            }
            QMessageBox.warning(self, title, reasons.get(payload) or tr(
                "The update could not be downloaded ({err}). Check your internet connection.", err=payload))
        elif kind == "hltb":
            self._updating = False
            old, new, err = msg[1]
            self.hide_notice()
            if err:
                QMessageBox.warning(self, tr("Update the HowLongToBeat connection"),
                                    tr("It could not be updated:\n\n{err}", err=err))
            elif old == new:
                QMessageBox.information(self, tr("Update the HowLongToBeat connection"),
                                        tr("The HowLongToBeat connection is already up to date (version {v}).", v=new or "?"))
            else:
                QMessageBox.information(self, tr("Update the HowLongToBeat connection"),
                                        tr("The HowLongToBeat connection was updated from version {old} to {new}.\n\n"
                                           "Close the app and open it again to use it.", old=old or "?", new=new or "?"))

    # ---- app updates ----
    def check_updates(self, *_):
        if self._updating:
            return
        self._updating = True
        self.show_notice(tr("Looking for a new version of the app…"))
        self._notice_timer.stop()

        def run():
            res = check_app_update()
            try:
                self.bridge.task.emit(("app_check", res))
            except RuntimeError:
                pass

        threading.Thread(target=run, daemon=True).start()

    def ask_update(self, info):
        """Show what is new and ask whether to update now."""
        notes = info.get("notes") or ""
        if len(notes) > 700:
            notes = notes[:700].rstrip() + "…"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("Check for updates"))
        text = tr("There is a new version: {new} (you have {old}).", new=info["version"], old=APP_VERSION)
        if notes:
            text += "\n\n" + tr("What is new:") + "\n" + notes
        text += "\n\n" + tr("It will be downloaded, the app will close and the new version will open. "
                              "Your games are not touched.")
        box.setText(text)
        yes = box.addButton(tr("Update now"), QMessageBox.ButtonRole.AcceptRole)
        yes.setObjectName("primary")
        no = box.addButton(tr("Not now"), QMessageBox.ButtonRole.RejectRole)
        no.setObjectName("ghost")
        box.setDefaultButton(yes)
        box.exec()
        return box.clickedButton() is yes

    def download_update(self, info):
        self._updating = True
        self._update_info = info
        self.show_notice(tr("Downloading version {v}…", v=info["version"]))
        self._notice_timer.stop()

        def progress(done, total):
            try:
                self.bridge.task.emit(("app_progress", done, total))
            except RuntimeError:
                pass

        def run():
            res = download_exe_update(info, progress) if is_exe() else install_pyw_update(info)
            try:
                self.bridge.task.emit(("app_ready", res))
            except RuntimeError:
                pass

        threading.Thread(target=run, daemon=True).start()

    def restart_into_update(self, new_path):
        """Close the app and open the new version (games and settings are saved on close)."""
        if is_exe():
            start_exe_swap(Path(sys.executable), new_path, os.getpid())
        else:
            subprocess.Popen([sys.executable, str(SCRIPT_PATH)],   # the same Python that runs the app now
                             creationflags=DETACHED | NO_WINDOW, close_fds=True)
        self.close()
        QApplication.instance().quit()

    def update_connections(self, *_):
        """Install the newest version of the library that reads HowLongToBeat."""
        if getattr(sys, "frozen", False):
            QMessageBox.information(self, tr("Update the HowLongToBeat connection"),
                                    tr("In the .exe version the connection is built into the program, so it cannot be "
                                       "updated from here: download the newest .exe. (With the Python version, "
                                       "mi_backlog_juegos.pyw, this option updates it by itself.)"))
            return
        if self._updating:
            return
        self._updating = True
        self.show_notice(tr("Looking for a new version of the HowLongToBeat connection…"))
        self._notice_timer.stop()

        def run():
            res = update_hltb_library()
            try:
                self.bridge.task.emit(("hltb", res))
            except RuntimeError:
                pass

        threading.Thread(target=run, daemon=True).start()

    def delete_selected(self, *_):
        gids = self.selected_ids() or ([self.current_id()] if self.current_id() else [])
        if gids:
            self.delete_games(gids)

    def edit_selected(self, *_):
        gid = self.current_id()
        if gid:
            self.edit_game(gid)

    def status_selected(self, status):
        gids = self.selected_ids() or ([self.current_id()] if self.current_id() else [])
        if gids:
            self.set_status_many(gids, status)

    def context_menu(self, pos):
        it = self.list.itemAt(pos)
        if not it:
            return
        sel = self.selected_ids()
        if it.isSelected() and len(sel) > 1:
            self.multi_menu(sel, pos)
            return
        gid = it.data(ROLE_ID)
        g = self.find(gid)
        if not g:
            return
        m = QMenu(self)
        style_menu(m)
        # the text after \t is only a hint shown on the right (the real shortcuts are on the list itself)
        a_edit = m.addAction(tr("Edit") + "\tEnter")
        a_edit.triggered.connect(lambda _=False: self.edit_game(gid))
        sub = m.addMenu(tr("Change status"))
        style_menu(sub)
        for n, s in enumerate(STATUSES, 1):
            act = sub.addAction(f"{status_label(s)}\t{n}")
            act.setCheckable(True)
            act.setChecked(g["status"] == s)
            act.triggered.connect(lambda _=False, s=s: self.set_status(gid, s))
        a_plat = m.addAction(tr("🏆  Platinum earned"))
        a_plat.setCheckable(True)
        a_plat.setChecked(bool(g.get("platinum")))
        a_plat.triggered.connect(lambda _=False: self.toggle_flag(gid, "platinum"))
        a_rerun = m.addAction(tr("🔁  Rerun (replaying)"))
        a_rerun.setCheckable(True)
        a_rerun.setChecked(bool(g.get("rerun")))
        a_rerun.triggered.connect(lambda _=False: self.toggle_flag(gid, "rerun"))
        move = m.addMenu(tr("Move to list"))
        style_menu(move)
        others = [y for y in self.years if y != g.get("year")]
        move.setEnabled(bool(others))
        for y in others:
            move.addAction(tr("List {year}", year=y)).triggered.connect(
                lambda _=False, y=y: self.move_to_year(gid, y))
        m.addSeparator()
        m.addAction(tr("Open Metacritic")).triggered.connect(
            lambda _=False: QDesktopServices.openUrl(QUrl(metacritic_search_url(g["name"]))))
        m.addAction(tr("Open HowLongToBeat")).triggered.connect(
            lambda _=False: QDesktopServices.openUrl(QUrl(hltb_url(g["name"], g.get("hltb_id")))))
        m.addSeparator()
        a_del = m.addAction(tr("Delete") + "\t" + tr("Del"))
        a_del.triggered.connect(lambda _=False: self.delete_game(gid))
        m.exec(self.list.viewport().mapToGlobal(pos))

    def multi_menu(self, gids, pos):
        """Right-click on several selected games."""
        m = QMenu(self)
        style_menu(m)
        head = m.addAction(tr("{n} games selected", n=len(gids)))
        head.setEnabled(False)
        m.addSeparator()
        sub = m.addMenu(tr("Change status"))
        style_menu(sub)
        for n, s in enumerate(STATUSES, 1):
            sub.addAction(f"{status_label(s)}\t{n}").triggered.connect(
                lambda _=False, s=s: self.set_status_many(gids, s))
        m.addAction(tr("Move or copy to another list…")).triggered.connect(
            lambda _=False: self.transfer_selected(gids))
        m.addSeparator()
        m.addAction(tr("Delete {n} games", n=len(gids)) + "\t" + tr("Del")).triggered.connect(
            lambda _=False: self.delete_games(gids))
        m.exec(self.list.viewport().mapToGlobal(pos))


def install_error_log():
    """An unexpected error is written to error.log instead of closing the app (PyQt6 aborts if nobody handles it)."""
    def hook(exc_type, exc, tb):
        try:
            import traceback
            ensure_dirs()
            with open(DATA_DIR / "error.log", "a", encoding="utf-8") as f:
                f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                f.write("".join(traceback.format_exception(exc_type, exc, tb)) + "\n")
        except Exception:
            pass
    sys.excepthook = hook


def apply_theme(app, code):
    """Colors, small icons and style sheet of the chosen theme."""
    global ASSETS
    set_theme(code)
    app.setPalette(build_palette())
    ASSETS = build_assets()
    app.setStyleSheet(build_style(ASSETS))
    _TIER_PIX.clear()


def main():
    global ASSETS
    install_error_log()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon())
    cfg = load_json(CONFIG_FILE, {})
    apply_theme(app, cfg.get("theme", "dark"))
    set_language(cfg.get("lang", "en"))   # English unless the user chose Spanish
    w = MainWindow()
    _WINDOWS.append(w)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
