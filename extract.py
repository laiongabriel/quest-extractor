#!/usr/bin/env python3
"""
extract.py
Extrai texto de um PDF de questões tratando páginas com duas colunas.
Salva questões em JSON estruturado, incluindo número da questão.

Uso: python extract.py <arquivo.pdf>
Saída: <basename>_output.json
"""
from __future__ import annotations
import sys, os, re, json

def extract_text_columns(path: str) -> str:
    try:
        import pdfplumber
    except Exception as e:
        raise RuntimeError("pdfplumber é necessário para este modo de extração.") from e

    print(f"Abrindo PDF: {path}")
    pages_text = []
    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        limit = min(total, 6)  # <<< temporário: lê no máximo 6 páginas
        print(f"PDF aberto. Número de páginas: {total}, lendo até {limit}...")

        for i, page in enumerate(pdf.pages[:limit], 1):
            w, h = page.width, page.height
            print(f"Processando página {i}/{limit}...")

            candidates = []
            lines = getattr(page, "lines", None)
            if lines is None:
                objs = getattr(page, "objects", None)
                if objs and "lines" in objs:
                    lines = objs["lines"]
                else:
                    lines = []

            for ln in lines:
                x0, x1 = ln.get("x0"), ln.get("x1")
                y0, y1 = ln.get("y0", 0), ln.get("y1", h)
                if x0 is None or x1 is None:
                    continue
                if abs(x0 - x1) < 4 and (y1 - y0) > 0.3 * h and 0.25 * w < x0 < 0.75 * w:
                    candidates.append(x0)

            if candidates:
                split_x = sorted(candidates, key=lambda x: abs(x - w/2))[0]
                print(f" Coluna detectada em x={split_x:.1f}")
            else:
                split_x = w / 2.0
                print(" Nenhuma linha central detectada, usando metade da página")

            gap = max(4.0, w * 0.01)
            left_bbox = (0, 0, max(0, split_x - gap), h)
            right_bbox = (min(w, split_x + gap), 0, w, h)

            left_text = page.crop(left_bbox).extract_text() or ""
            right_text = page.crop(right_bbox).extract_text() or ""

            if (not left_text.strip() or not right_text.strip()) and split_x != w/2.0:
                split_x = w / 2.0
                left_bbox = (0, 0, split_x - gap, h)
                right_bbox = (split_x + gap, 0, w, h)
                left_text = page.crop(left_bbox).extract_text() or ""
                right_text = page.crop(right_bbox).extract_text() or ""
                print(" Ajuste: fallback para dividir a página ao meio")

            page_text = (left_text.strip() + "\n\n" + right_text.strip()).strip()
            pages_text.append(page_text)

    print("Extração de texto concluída.")
    return "\n\n".join([p for p in pages_text if p])


def normalize_keep_lines(s: str) -> str:
    print("Normalizando texto...")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r'-\n', '', s)  # junta palavras quebradas
    s = re.sub(r'[ \t]+', ' ', s)  # remove espaços duplicados
    s = re.sub(r'\n{3,}', '\n\n', s)  # mais de 2 quebras -> 2

    # remove a string "ular" solta
    s = re.sub(r'(?<=\s)ular(?=\s|\n|$)', '', s)

    return s.strip()


def split_questions(full_text: str):
    print("Dividindo texto em questões...")
    pattern = re.compile(r'(?m)^\s*(\d+)\.\s*')
    matches = list(pattern.finditer(full_text))
    questions = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i+1].start() if i+1 < len(matches) else len(full_text)
        qtext = full_text[start:end].strip()
        questions.append((int(m.group(1)), qtext))
    print(f" Total de questões detectadas: {len(questions)}")
    return questions


def parse_question_block(qtext: str):
    """
    Identifica enunciado e alternativas.
    Evita cortar frases com (a) dentro de parênteses
    Suporta alternativas na mesma linha ou em linhas separadas
    Suporta até a alternativa F
    """
    opt_pattern = re.compile(
        r'(?i)(?:(?<=^)|(?<=[\s\.]))([a-fA-F])\)\s*(.*?)(?=(?:[\s\.][a-fA-F]\)|$))',
        re.DOTALL
    )

    first_match = opt_pattern.search(qtext)
    if first_match:
        alt_start = first_match.start()
        enunciado = qtext[:alt_start].strip()
    else:
        enunciado = qtext.strip()

    alternatives = {}
    for letter, val in opt_pattern.findall(qtext):
        alternatives[f"alternativa_{letter.lower()}"] = val.strip()

    return enunciado, alternatives


def collapse_single_linebreaks(text: str) -> str:
    # Substitui quebras simples por espaço, mantendo duplas
    return re.sub(r'(?<!\n)\n(?!\n)', ' ', text)


def main(argv):
    if len(argv) < 2:
        print("Uso: python extract.py <arquivo.pdf>")
        return 1

    path = argv[1]
    if not os.path.isfile(path):
        print("Arquivo não encontrado:", path)
        return 1

    raw = extract_text_columns(path)
    norm = normalize_keep_lines(raw)
    qlist = split_questions(norm)[:100]

    print(f"Preparando {len(qlist)} primeiras questões para salvar...")
    output = []
    for numero, qtext in qlist:
        enunciado, alternatives = parse_question_block(qtext)

        # Aplica a substituição de quebras simples por espaço no JSON
        enunciado = collapse_single_linebreaks(enunciado)
        alternatives = {k: collapse_single_linebreaks(v) for k, v in alternatives.items()}

        output.append({
            "numero_questao": numero,
            "enunciado": enunciado,
            "imagem": "",
            "alternativas": alternatives,
            "alternativa_correta": ""
        })

    base = os.path.splitext(os.path.basename(path))[0]
    out_path = os.path.join(os.path.dirname(path), f"{base}_output.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Concluído! {len(output)} questões salvas em: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
