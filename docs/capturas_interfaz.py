"""Toma capturas de la interfaz de DataVoz para el documento (Chrome headless + Selenium).

Requisitos: la app corriendo (streamlit run app.py) y `pip install selenium`.
Uso:  python docs/capturas_interfaz.py [--url http://localhost:8501]
Guarda las imágenes en docs/img/. Hace 2 preguntas reales (gasta ~6 llamadas al LLM).
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

DIR_IMG = Path(__file__).resolve().parent / "img"


def esperar_respuesta(driver, n_mensajes: int, limite: float = 120) -> None:
    """Espera a que haya n mensajes del asistente y ningún estado «trabajando»."""
    inicio = time.time()
    while time.time() - inicio < limite:
        mensajes = driver.find_elements(By.CSS_SELECTOR, '[data-testid="stChatMessage"]')
        trabajando = driver.find_elements(By.XPATH, "//*[contains(text(), 'trabajando')]")
        if len(mensajes) >= n_mensajes and not trabajando:
            time.sleep(3)
            return
        time.sleep(1)
    raise TimeoutError("La app no respondió a tiempo")


def preguntar(driver, texto: str, n_mensajes: int) -> None:
    caja = WebDriverWait(driver, 30).until(EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-testid="stChatInputTextArea"]')))
    caja.click()
    caja.send_keys(texto)
    caja.send_keys(Keys.ENTER)
    time.sleep(2)
    esperar_respuesta(driver, n_mensajes)


def pestaña(driver, texto: str) -> None:
    driver.execute_script("window.scrollTo(0, 0)")
    for t in driver.find_elements(By.XPATH, f"//*[@role='tab'][contains(., '{texto}')]"):
        driver.execute_script("arguments[0].click();", t)
        time.sleep(3)
        driver.execute_script("window.scrollTo(0, 0)")
        return


def captura(driver, nombre: str, alto: int | None = None) -> None:
    if alto:
        driver.set_window_size(1400, alto)
        time.sleep(2)
    driver.save_screenshot(str(DIR_IMG / nombre))
    print("ok", DIR_IMG / nombre)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8501")
    args = ap.parse_args()
    DIR_IMG.mkdir(parents=True, exist_ok=True)
    opciones = webdriver.ChromeOptions()
    opciones.add_argument("--headless=new")
    opciones.add_argument("--window-size=1400,1000")
    opciones.add_argument("--force-device-scale-factor=1")
    driver = webdriver.Chrome(options=opciones)
    try:
        driver.get(args.url)
        WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="stChatInputTextArea"]')))
        time.sleep(3)
        # La app reabre la última sesión guardada: se empieza una nueva para que las capturas sean limpias
        for b in driver.find_elements(By.XPATH, "//section[@data-testid='stSidebar']//button[contains(., 'Nueva')]"):
            driver.execute_script("arguments[0].click();", b)
            time.sleep(4)
            break
        captura(driver, "01_inicio.png")
        preguntar(driver, "¿Qué bebida se vendió menos en diciembre y por qué crees que pasó?", 2)
        driver.execute_script("window.scrollTo(0, 0)")
        captura(driver, "02_respuesta.png", alto=1250)
        preguntar(driver, "¿Cómo fueron las ventas mes por mes?", 4)
        pestaña(driver, "Dashboard")
        captura(driver, "03_dashboard.png", alto=1150)
        pestaña(driver, "Trazas")
        captura(driver, "04_trazas.png", alto=900)
    finally:
        driver.quit()

    # Ventana nueva = como cerrar y volver a abrir la app: debe reabrir la sesión guardada
    driver = webdriver.Chrome(options=opciones)
    try:
        driver.get(args.url)
        WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="stChatInputTextArea"]')))
        time.sleep(8)
        captura(driver, "05_sesion_reabierta.png", alto=1000)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
