"""
sales_text.py
---------------
Erzeugt einen fertigen Verkaufstext aus den erkannten/eingegebenen Daten.
Funktioniert komplett offline per Textbaustein (keine externe API noetig).
"""


def generate_sales_text(
    card_name: str,
    set_info: str = "",
    grading_company: str = "",
    grade: str = "",
    reference_price: str = "",
    condition_note: str = "",
) -> str:
    lines = [card_name.strip() or "Pokemonkarte"]

    if set_info.strip():
        lines.append(set_info.strip())

    if grading_company.strip() and grade.strip():
        lines.append(f"{grading_company.strip()} {grade.strip()}")
    elif grade.strip():
        lines.append(f"Grade: {grade.strip()}")

    listing = "\n".join(lines)

    extras = []
    if reference_price:
        extras.append(f"Richtpreis (pricecharting.com): {reference_price}")
    if condition_note.strip():
        extras.append(f"Zustand: {condition_note.strip()}")
    extras_block = ("\n".join(extras) + "\n\n") if extras else ""

    shipping = (
        "Versandhinweis:\n"
        "Versand ist möglich - wahlweise als unversicherter Brief (günstiger, "
        "aber ohne Sendungsverfolgung/Versicherung im Verlustfall) oder "
        "versichert/nachverfolgbar (z. B. Einschreiben). Sag mir gerne, was "
        "du bevorzugst."
    )

    text = f"{listing}\n\n{extras_block}{shipping}\n\nBei Fragen gerne melden!"
    return text
