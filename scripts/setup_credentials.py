"""
setup_credentials.py
====================
Guarda credenciales de NetX360+ y Gmail en Windows Credential Manager de forma
encriptada (via keyring). Corre 1 vez.

Uso:
    python scripts/setup_credentials.py
    # Te pide user + password interactivamente (los tipeas, no se muestran)
    # Se guardan en el vault de Windows
    # Nadie mas puede leerlos sin login a tu cuenta Windows
"""
import getpass
import keyring


def prompt_and_save(service_name: str, key: str, label: str, hide: bool = True):
    if hide:
        value = getpass.getpass(f"  {label}: ").strip()
    else:
        value = input(f"  {label}: ").strip()
    if not value:
        print(f"  ! Vacio, no se guarda")
        return
    keyring.set_password(service_name, key, value)
    print(f"  [OK] Guardado en Windows Credential Manager: {service_name}/{key}")


def main():
    print("=" * 60)
    print("SETUP CREDENCIALES - Big Dashboard")
    print("=" * 60)
    print()
    print("Los datos se guardan encriptados en Windows Credential Manager.")
    print("Solo tu usuario de Windows puede leerlos. Nadie mas.")
    print()

    print("[1] NetX360+ (advisor login):")
    prompt_and_save("big-netx360", "user", "Usuario NetX360+", hide=False)
    prompt_and_save("big-netx360", "pass", "Password NetX360+", hide=True)
    print()

    print("[2] Gmail App Password (para leer OTPs):")
    print("    Antes de continuar, generá un App Password en:")
    print("    https://myaccount.google.com/apppasswords")
    print("    (requiere 2FA activo en tu cuenta Google)")
    print("    Copiá el password de 16 caracteres que te da Google.")
    print()
    prompt_and_save("big-gmail-otp", "email", "Tu Gmail (monpelatlucas@gmail.com)", hide=False)
    prompt_and_save("big-gmail-otp", "apppass", "App Password de 16 chars", hide=True)
    print()

    print("=" * 60)
    print("VERIFY:")
    print("=" * 60)
    for svc, key in [("big-netx360", "user"), ("big-netx360", "pass"),
                     ("big-gmail-otp", "email"), ("big-gmail-otp", "apppass")]:
        v = keyring.get_password(svc, key)
        masked = v[:3] + "***" if v and len(v) > 3 else "(vacio)"
        print(f"  {svc}/{key}: {masked}")

    print()
    print("[OK] Setup completo. Podes correr los scrapers ahora.")


if __name__ == "__main__":
    main()
