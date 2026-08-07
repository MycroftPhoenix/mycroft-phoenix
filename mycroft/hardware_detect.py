"""
Detection universelle du materiel.
Fonctionne sur n'importe quelle machine : AMD, Intel, ARM, etc.
Zero configuration — detecte automatiquement au demarrage.
"""

import os
import sys
import json
import platform
import subprocess
import logging
from datetime import datetime

logger = logging.getLogger("phoenix.hardware")

# Profils materiels auto-attribues
PROFILES = {
    "OPENCL_APU":       "APU avec GPU integre + OpenCL",
    "AVX2_MODERN":      "Processeur x86 moderne (AVX2+FMA3)",
    "AVX_LEGACY":       "Processeur x86 ancien (AVX sans AVX2)",
    "SSE_ONLY":         "Processeur x86 tres ancien (SSE uniquement)",
    "ARM_NEON":         "Processeur ARM avec NEON",
    "ARM_LOW_POWER":    "Processeur ARM basse consommation",
    "APPLE_SILICON":    "Apple Silicon (M1/M2/M3/M4)",
    "GENERIC":          "Materiel inconnu — mode degrades",
}


def detect_hardware():
    """
    Detecte le materiel et retourne un dict structur.
    Marche sur Windows, Linux, macOS.
    """
    info = {
        "cpu_name": "Inconnu",
        "vendor": "Inconnu",
        "arch": platform.machine().lower(),
        "os": platform.system(),
        "instructions": [],
        "gpu": None,
        "opencl": False,
        "ram_mb": 0,
        "cores": 0,
        "logical_cores": 0,
        "profile": "GENERIC",
        "detected_at": datetime.now().isoformat(),
    }

    # CPU
    _detect_cpu(info)

    # GPU / OpenCL
    _detect_gpu(info)

    # RAM
    _detect_ram(info)

    # Profil automatique
    _assign_profile(info)

    logger.info(
        "Materiel detecte: %s | CPU: %s | GPU: %s | Profil: %s",
        info["arch"], info["cpu_name"], info["gpu"] or "Aucun", info["profile"]
    )

    return info


def _detect_cpu(info):
    """Detecte le CPU et ses instructions."""
    system = platform.system()

    if system == "Linux":
        _detect_cpu_linux(info)
    elif system == "Windows":
        _detect_cpu_windows(info)
    elif system == "Darwin":
        _detect_cpu_macos(info)
    else:
        logger.warning("OS non supporte pour detection CPU: %s", system)


def _detect_cpu_linux(info):
    """Lit /proc/cpuinfo sur Linux."""
    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                line = line.strip().lower()
                if line.startswith("model name"):
                    info["cpu_name"] = line.split(":", 1)[1].strip()
                elif line.startswith("vendor_id"):
                    info["vendor"] = line.split(":", 1)[1].strip()
                elif line.startswith("flags") or line.startswith("features"):
                    info["instructions"] = line.split(":", 1)[1].strip().split()
                elif line.startswith("cpu cores"):
                    info["cores"] = int(line.split(":", 1)[1].strip())
                elif line.startswith("siblings"):
                    info["logical_cores"] = int(line.split(":", 1)[1].strip())
    except Exception as e:
        logger.error("Erreur lecture /proc/cpuinfo: %s", e)


def _detect_cpu_windows(info):
    """Detecte le CPU sous Windows via wmic + registry."""
    # Nom + vendor via wmic
    try:
        result = subprocess.run(
            ["wmic", "cpu", "get", "Name,Manufacturer,NumberOfCores,NumberOfLogicalProcessors", "/format:list"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("Name="):
                info["cpu_name"] = line.split("=", 1)[1].strip()
            elif line.startswith("Manufacturer="):
                mfr = line.split("=", 1)[1].strip()
                if "AMD" in mfr.upper():
                    info["vendor"] = "AuthenticAMD"
                elif "Intel" in mfr.upper():
                    info["vendor"] = "GenuineIntel"
                else:
                    info["vendor"] = mfr
            elif line.startswith("NumberOfCores="):
                info["cores"] = int(line.split("=", 1)[1].strip() or 0)
            elif line.startswith("NumberOfLogicalProcessors="):
                info["logical_cores"] = int(line.split("=", 1)[1].strip() or 0)
    except Exception as e:
        logger.error("Erreur wmic: %s", e)

    # Instructions via registry (FeatureSet)
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        )
        feature_set, _ = winreg.QueryValueEx(key, "FeatureSet")
        winreg.CloseKey(key)
        info["instructions"] = _decode_feature_set(feature_set)
    except Exception as e:
        logger.debug("Registry CPU non lisible: %s", e)


def _decode_feature_set(feature_set):
    """Decode les bits de feature set Windows en noms d'instructions."""
    flags = []
    # Bits standard du FeatureSet Windows
    bit_map = {
        0: "fpu", 1: "vme", 2: "de", 3: "pse", 4: "tsc", 5: "msr",
        6: "pae", 7: "mce", 8: "cx8", 9: "apic", 11: "sep",
        12: "mtrr", 13: "pge", 14: "mca", 15: "cmov", 16: "pat",
        17: "pse36", 19: "clflush", 23: "mmx", 24: "fxsr",
        25: "sse", 26: "sse2",
    }
    for bit, name in bit_map.items():
        if feature_set & (1 << bit):
            flags.append(name)

    # Pour SSE3+ il faut CPUID leaf 1 — on approxime avec le vendor
    # Les CPUs modernes avec SSE2 ont presque toujours SSE3+
    if "sse2" in flags:
        for extra in ["sse3", "ssse3", "sse4.1", "sse4.2", "avx", "avx2", "fma3"]:
            if extra not in flags:
                flags.append(extra)  # approximation conservative
    return flags


def _detect_cpu_macos(info):
    """Detecte le CPU sur macOS via sysctl."""
    try:
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True, text=True, timeout=5
        )
        info["cpu_name"] = result.stdout.strip()

        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.features"],
            capture_output=True, text=True, timeout=5
        )
        info["instructions"] = result.stdout.strip().lower().split()

        # Apple Silicon ?
        if "Apple" in info["cpu_name"]:
            info["vendor"] = "Apple"
    except Exception as e:
        logger.error("Erreur sysctl: %s", e)


def _detect_gpu(info):
    """Detecte le GPU et OpenCL."""
    system = platform.system()

    if system == "Windows":
        _detect_gpu_windows(info)
    elif system == "Linux":
        _detect_gpu_linux(info)
    elif system == "Darwin":
        _detect_gpu_macos(info)


def _detect_gpu_windows(info):
    """Detecte le GPU sous Windows."""
    try:
        result = subprocess.run(
            ["wmic", "path", "win32_videocontroller", "get", "Name", "/format:list"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("Name=") and not info["gpu"]:
                info["gpu"] = line.split("=", 1)[1].strip()
    except Exception as e:
        logger.debug("Detection GPU Windows: %s", e)

    # OpenCL — verifier si le runtime est installe
    try:
        result = subprocess.run(
            ["wmic", "path", "win32_sysdriver", "get", "Name"],
            capture_output=True, text=True, timeout=10
        )
        if "opencl" in result.stdout.lower() or "atijob" in result.stdout.lower():
            info["opencl"] = True
    except Exception:
        pass

    # Fallback: verifier les DLLs OpenCL
    if not info["opencl"]:
        for dll in ["OpenCL.dll", "opencl.dll"]:
            try:
                ctypes_path = os.path.join(
                    os.environ.get("SYSTEMROOT", r"C:\Windows"),
                    "System32", dll
                )
                if os.path.exists(ctypes_path):
                    info["opencl"] = True
                    break
            except Exception:
                pass


def _detect_gpu_linux(info):
    """Detecte le GPU sous Linux."""
    try:
        result = subprocess.run(
            ["lspci"], capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            if "VGA" in line or "3D" in line or "Display" in line:
                info["gpu"] = line.split(":", 2)[-1].strip() if ":" in line else line.strip()
                break
    except Exception:
        pass

    # OpenCL
    try:
        result = subprocess.run(["clinfo", "--list"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            info["opencl"] = True
    except Exception:
        pass


def _detect_gpu_macos(info):
    """Detecte le GPU sur macOS."""
    try:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            if "Chipset Model:" in line or "Chip:" in line:
                info["gpu"] = line.split(":", 1)[1].strip()
                break
    except Exception:
        pass

    # Apple Silicon a Metal (pas OpenCL)
    if info["gpu"] and "Apple" in info["gpu"]:
        info["opencl"] = False  # Metal uniquement


def _detect_ram(info):
    """Detecte la RAM totale en MB."""
    system = platform.system()

    try:
        if system == "Windows":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            c_ulonglong = ctypes.c_ulonglong
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", c_ulonglong),
                    ("ullAvailPhys", c_ulonglong),
                    ("ullTotalPageFile", c_ulonglong),
                    ("ullAvailPageFile", c_ulonglong),
                    ("ullTotalVirtual", c_ulonglong),
                    ("ullAvailVirtual", c_ulonglong),
                    ("ullAvailExtendedVirtual", c_ulonglong),
                ]
            mem = MEMORYSTATUSEX()
            mem.dwLength = ctypes.sizeof(mem)
            kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
            info["ram_mb"] = mem.ullTotalPhys // (1024 * 1024)

        elif system == "Linux":
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        kb = int(line.split()[1])
                        info["ram_mb"] = kb // 1024
                        break

        elif system == "Darwin":
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=5
            )
            bytes_ram = int(result.stdout.strip())
            info["ram_mb"] = bytes_ram // (1024 * 1024)

    except Exception as e:
        logger.warning("Detection RAM echouee: %s", e)


def _assign_profile(info):
    """Attribue un profil automatique selon le materiel detecte."""
    arch = info["arch"].lower()
    vendor = info["vendor"]
    instructions = info["instructions"]

    # ARM
    if "arm" in arch or "aarch64" in arch:
        if vendor == "Apple":
            info["profile"] = "APPLE_SILICON"
        elif info["ram_mb"] and info["ram_mb"] < 4096:
            info["profile"] = "ARM_LOW_POWER"
        else:
            info["profile"] = "ARM_NEON"
        return

    # x86/x86_64
    if info["opencl"] and "AMD" in vendor.upper():
        info["profile"] = "OPENCL_APU"
    elif "avx2" in instructions and "fma3" in instructions:
        info["profile"] = "AVX2_MODERN"
    elif "avx" in instructions:
        info["profile"] = "AVX_LEGACY"
    elif "sse2" in instructions:
        info["profile"] = "SSE_ONLY"
    else:
        info["profile"] = "GENERIC"


def format_hardware_summary(info):
    """Formate un resume lisible du materiel detecte."""
    lines = []
    lines.append(f"CPU: {info['cpu_name']}")
    lines.append(f"Arch: {info['arch']} | Vendor: {info['vendor']}")
    lines.append(f"Coeurs: {info['cores']} phys / {info['logical_cores']} logiques")
    lines.append(f"RAM: {info['ram_mb']} Mo")
    if info["gpu"]:
        lines.append(f"GPU: {info['gpu']}")
    lines.append(f"OpenCL: {'Oui' if info['opencl'] else 'Non'}")
    lines.append(f"Profil: {info['profile']} — {PROFILES.get(info['profile'], '')}")

    # Instructions importantes
    important = [i for i in info["instructions"]
                 if i in ("sse", "sse2", "sse3", "avx", "avx2", "fma3", "neon", "aes")]
    if important:
        lines.append(f"Instructions: {', '.join(important)}")

    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    info = detect_hardware()
    print()
    print("=" * 50)
    print("  PHOENIX — Detection materielle")
    print("=" * 50)
    print()
    print(format_hardware_summary(info))
    print()
    print(json.dumps(info, indent=2, ensure_ascii=False))
