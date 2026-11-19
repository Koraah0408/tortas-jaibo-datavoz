"""Genera las notas de voz de los casos de prueba con la voz es-MX de Windows (SAPI, local).

Los audios ya vienen incluidos en evaluacion/audio/, así que este script solo es
necesario si se cambian las preguntas. Requiere Windows con la voz
"Microsoft Sabina" (español de México) instalada.

Uso:  python scripts/generar_audios_prueba.py
"""

import subprocess
import sys
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[1]
DIR_AUDIO = RAIZ / "evaluacion" / "audio"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def sintetizar(texto: str, destino: Path, velocidad: int = 0) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    texto_ps = texto.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'es-*' } | Select-Object -First 1; "
        "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }; "
        f"$s.Rate = {velocidad}; "
        f"$s.SetOutputToWaveFile('{destino}'); "
        f"$s.Speak('{texto_ps}'); $s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)


def main() -> None:
    casos = yaml.safe_load((RAIZ / "evaluacion" / "casos_prueba.yaml").read_text(encoding="utf-8"))
    for caso in casos["casos"]:
        if caso.get("audio") and caso.get("texto_hablado"):
            destino = RAIZ / caso["audio"]
            sintetizar(caso["texto_hablado"], destino)
            print(f"✓ {destino.relative_to(RAIZ)}  ←  {caso['texto_hablado']}")


if __name__ == "__main__":
    if sys.platform != "win32":
        sys.exit("Este script usa la síntesis de voz de Windows (SAPI).")
    main()
