#!/usr/bin/env python3
"""
extract.py

Extrai texto de um PDF de questões tratando páginas com duas colunas.
1. Detecta retângulos roxos (#9c28b0)
2. Extrai conteúdo como imagem base64 (removendo bordas roxas)
3. Remove retângulos do PDF para não interferir na extração de texto
4. Associa cada imagem à questão correspondente

Uso: python extract.py <arquivo.pdf>
Saída: <basename>_output.json
"""
from __future__ import annotations
import sys, os, re, json
import tempfile
import base64
from io import BytesIO

def rgb_distance(color1, color2):
    """Calcula distância euclidiana entre duas cores RGB (0-1)"""
    return sum((a - b) ** 2 for a, b in zip(color1, color2)) ** 0.5

def is_purple_color(color, target_rgb=(0x9c/255, 0x28/255, 0xb0/255), threshold=0.15):
    """
    Verifica se uma cor está próxima do roxo #9c28b0
    color: tupla RGB normalizada (0-1)
    threshold: distância máxima aceita (0.15 é tolerante a variações)
    """
    if not color or len(color) < 3:
        return False
    return rgb_distance(color[:3], target_rgb) < threshold

def extract_and_remove_purple_rectangles(pdf_path: str):
    """
    1. Detecta retângulos roxos e extrai como imagens base64
    2. Remove os retângulos do PDF (cria PDF limpo)
    
    Retorna: (caminho_pdf_limpo, lista_imagens)
    lista_imagens = [{"page": 1, "rect": (x0,y0,x1,y1), "b64": "...", "y_center": float}]
    """
    try:
        import fitz  # PyMuPDF
        from PIL import Image
    except ImportError as e:
        raise RuntimeError("PyMuPDF e Pillow são necessários. Instale com: pip install PyMuPDF Pillow") from e
    
    print(f"\n[PyMuPDF] Abrindo PDF: {pdf_path}")
    doc = fitz.open(pdf_path)
    
    purple_images = []
    total_removed = 0
    
    for page_num, page in enumerate(doc, 1):
        print(f"[PyMuPDF] Processando página {page_num}/{len(doc)}...")
        
        drawings = page.get_drawings()
        print(f"  Total de objetos vetoriais: {len(drawings)}")
        
        page_rects = []
        
        for drawing in drawings:
            fill_color = drawing.get("fill")
            stroke_color = drawing.get("color")
            
            is_purple = False
            
            if fill_color and is_purple_color(fill_color):
                is_purple = True
                color_type = "fill"
            elif stroke_color and is_purple_color(stroke_color):
                is_purple = True
                color_type = "stroke"
            
            if is_purple:
                rect = drawing.get("rect")
                if rect:
                    page_rects.append((rect, color_type))
        
        # Processa cada retângulo roxo encontrado
        for rect, color_type in page_rects:
            # ETAPA 1: EXTRAI IMAGEM do retângulo
            margin = 3  # pequena margem para capturar conteúdo
            expanded_rect = fitz.Rect(
                max(0, rect.x0 - margin),
                max(0, rect.y0 - margin),
                min(page.rect.width, rect.x1 + margin),
                min(page.rect.height, rect.y1 + margin)
            )
            
            # Renderiza a área como imagem de alta qualidade (200 DPI)
            pix = page.get_pixmap(clip=expanded_rect, dpi=200)
            
            # Converte para PIL Image para processar
            img_data = pix.tobytes("png")
            pil_img = Image.open(BytesIO(img_data))
            
            # Remove bordas roxas: substitui roxo por branco
            pil_img = pil_img.convert("RGB")
            pixels = pil_img.load()
            width, height = pil_img.size
            
            # Define cor roxa em RGB (156, 40, 176)
            purple_rgb = (156, 40, 176)
            threshold = 50  # tolerância para variações
            
            for y in range(height):
                for x in range(width):
                    r, g, b = pixels[x, y]
                    # Se a cor está próxima do roxo, substitui por branco
                    if (abs(r - purple_rgb[0]) < threshold and 
                        abs(g - purple_rgb[1]) < threshold and 
                        abs(b - purple_rgb[2]) < threshold):
                        pixels[x, y] = (255, 255, 255)
            
            # Converte para base64
            buffer = BytesIO()
            pil_img.save(buffer, format="PNG", optimize=True)
            img_bytes = buffer.getvalue()
            b64_str = base64.b64encode(img_bytes).decode('utf-8')
            
            # Calcula posição vertical central (para matching)
            y_center = (rect.y0 + rect.y1) / 2
            
            # Detecta coluna (esquerda/direita)
            page_width = page.rect.width
            center_x = (rect.x0 + rect.x1) / 2
            col_hint = "left" if center_x < page_width / 2 else "right"
            
            purple_images.append({
                "page": page_num,
                "rect": (rect.x0, rect.y0, rect.x1, rect.y1),
                "b64": b64_str,
                "y_center": y_center,
                "col_hint": col_hint
            })
            
            print(f"    ✓ Imagem extraída ({color_type}): "
                  f"página={page_num}, "
                  f"rect=({rect.x0:.1f}, {rect.y0:.1f}, {rect.x1:.1f}, {rect.y1:.1f}), "
                  f"coluna={col_hint}, "
                  f"tamanho={len(b64_str)} chars")
            
            # ETAPA 2: REMOVE o retângulo do PDF (pinta de branco)
            page.add_redact_annot(rect, fill=(1, 1, 1))
            total_removed += 1
        
        # Aplica as remoções na página
        if page_rects:
            page.apply_redactions()
            print(f"  → {len(page_rects)} retângulos processados (extraídos + removidos)")
    
    # Salva PDF limpo
    temp_fd, temp_path = tempfile.mkstemp(suffix=".pdf", prefix="cleaned_")
    os.close(temp_fd)
    doc.save(temp_path)
    doc.close()
    
    print(f"\n[PyMuPDF] ✓ PDF limpo salvo: {temp_path}")
    print(f"[PyMuPDF] ✓ Total de imagens extraídas: {len(purple_images)}")
    print(f"[PyMuPDF] ✓ Total de retângulos removidos: {total_removed}\n")
    
    return temp_path, purple_images

def extract_text_columns_with_positions(path: str):
    """
    Extrai texto mantendo informações de posição das questões.
    Retorna: (texto_completo, question_positions)
    question_positions = {numero_questao: {"page": 1, "y_start": float, "col": "left"}}
    """
    try:
        import pdfplumber
    except Exception as e:
        raise RuntimeError("pdfplumber é necessário.") from e

    print(f"[pdfplumber] Abrindo PDF limpo: {path}")
    pages_text = []
    question_positions = {}

    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        limit = min(total, 2)  # lê no máximo 2 páginas
        print(f"[pdfplumber] Páginas: {total}, lendo até {limit}...")

        for i, page in enumerate(pdf.pages[:limit], 1):
            w, h = page.width, page.height
            print(f"[pdfplumber] Processando página {i}/{limit}...")

            # Detecta coluna central
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

                # Ignora linha horizontal do rodapé
                if abs(y1 - y0) < 2 and y0 > h * 0.95:
                    continue

                # Detecta linha central vertical
                if abs(x0 - x1) < 4 and (y1 - y0) > 0.3 * h and 0.25 * w < x0 < 0.75 * w:
                    candidates.append(x0)

            if candidates:
                split_x = sorted(candidates, key=lambda x: abs(x - w / 2))[0]
                print(f"  Coluna detectada em x={split_x:.1f}")
            else:
                split_x = w / 2.0
                print("  Usando metade da página")

            gap = max(4.0, w * 0.01)
            left_bbox = (0, 0, max(0, split_x - gap), h)
            right_bbox = (min(w, split_x + gap), 0, w, h)

            # Extrai texto
            left_text = page.crop(left_bbox).extract_text() or ""
            right_text = page.crop(right_bbox).extract_text() or ""

            # Extrai palavras com posição
            left_words = page.crop(left_bbox).extract_words() or []
            right_words = page.crop(right_bbox).extract_words() or []

            if (not left_text.strip() or not right_text.strip()) and split_x != w / 2.0:
                split_x = w / 2.0
                left_bbox = (0, 0, split_x - gap, h)
                right_bbox = (split_x + gap, 0, w, h)
                left_text = page.crop(left_bbox).extract_text() or ""
                right_text = page.crop(right_bbox).extract_text() or ""
                left_words = page.crop(left_bbox).extract_words() or []
                right_words = page.crop(right_bbox).extract_words() or []

            # Detecta início de questões (padrão: "número.")
            question_pattern = re.compile(r'^\s*(\d+)\.\s')
            
            # Processa coluna esquerda
            for word in left_words:
                text = word.get("text", "")
                match = question_pattern.match(text)
                if match:
                    q_num = int(match.group(1))
                    question_positions[q_num] = {
                        "page": i,
                        "y_start": word.get("top", 0),
                        "col": "left"
                    }
            
            # Processa coluna direita
            for word in right_words:
                text = word.get("text", "")
                match = question_pattern.match(text)
                if match:
                    q_num = int(match.group(1))
                    question_positions[q_num] = {
                        "page": i,
                        "y_start": word.get("top", 0),
                        "col": "right"
                    }

            page_text = (left_text.strip() + "\n" + right_text.strip()).strip()
            pages_text.append(page_text)

    print("[pdfplumber] Extração concluída.")
    print(f"[pdfplumber] Posições detectadas: {len(question_positions)} questões")
    
    full_text = "\n\n".join([p for p in pages_text if p])
    return full_text, question_positions

def normalize_keep_lines(s: str) -> str:
    print("Normalizando texto...")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r'-\n', '', s)
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
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
    print(f"  Total de questões detectadas: {len(questions)}")
    return questions

def match_image_to_question(q_num: int, question_positions: dict, purple_images: list) -> str:
    """
    Associa uma imagem roxa à questão baseado em:
    - Mesma página
    - Mesma coluna (left/right)
    - Proximidade vertical (y_center da imagem próximo ao y_start da questão)
    
    Retorna: string base64 ou ""
    """
    if q_num not in question_positions:
        return ""
    
    q_info = question_positions[q_num]
    q_page = q_info["page"]
    q_y = q_info["y_start"]
    q_col = q_info["col"]
    
    # Calcula y_end aproximado (assume 100 pontos de altura por questão)
    q_y_end = q_y + 100
    
    # Filtra imagens da mesma página e coluna
    candidates = [
        img for img in purple_images 
        if img["page"] == q_page and img["col_hint"] == q_col
    ]
    
    # Procura imagem cuja y_center está dentro do range da questão
    margin = 50  # margem de tolerância
    for img in candidates:
        y_center = img["y_center"]
        
        if q_y - margin <= y_center <= q_y_end + margin:
            print(f"    ✓ Imagem associada à questão {q_num}: "
                  f"página={q_page}, coluna={q_col}, "
                  f"y_questão={q_y:.1f}, y_imagem={y_center:.1f}")
            return img["b64"]
    
    return ""

def parse_question_block(qtext: str):
    """Identifica enunciado e alternativas."""
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

def wrap_html_paragraphs(text: str) -> str:
    """Envolve cada bloco em <p>...</p>"""
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    return "".join(f"<p>{p}</p>" for p in parts)

def main(argv):
    if len(argv) < 2:
        print("Uso: python extract.py <arquivo.pdf>")
        return 1
    
    path = argv[1]
    if not os.path.isfile(path):
        print("Arquivo não encontrado:", path)
        return 1
    
    # PASSO 1: Extrai imagens dos retângulos roxos E cria PDF limpo
    cleaned_pdf_path, purple_images = extract_and_remove_purple_rectangles(path)
    
    try:
        # PASSO 2: Extrai texto do PDF limpo com posições
        raw, question_positions = extract_text_columns_with_positions(cleaned_pdf_path)
        norm = normalize_keep_lines(raw)
        qlist = split_questions(norm)[:100]
        
        print(f"\n[Montagem] Preparando {len(qlist)} questões para salvar...")
        
        output = []
        images_matched = 0
        
        for numero, qtext in qlist:
            enunciado, alternatives = parse_question_block(qtext)
            
            # PASSO 3: Associa imagem à questão
            image_b64 = match_image_to_question(numero, question_positions, purple_images)
            if image_b64:
                images_matched += 1
            
            # Envolve em HTML
            enunciado_html = wrap_html_paragraphs(enunciado)
            alternatives_html = {k: wrap_html_paragraphs(v) for k, v in alternatives.items()}
            
            output.append({
                "numero_questao": numero,
                "enunciado": enunciado_html,
                "imagem": image_b64,
                "alternativas": alternatives_html,
                "alternativa_correta": ""
            })
        
        base = os.path.splitext(os.path.basename(path))[0]
        out_path = os.path.join(os.path.dirname(path), f"{base}_output.json")
        
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        
        print(f"\n{'='*60}")
        print(f"✓ Concluído!")
        print(f"✓ Questões salvas: {len(output)}")
        print(f"✓ Questões com imagens: {images_matched}/{len(output)}")
        print(f"✓ Arquivo: {out_path}")
        print(f"{'='*60}\n")
        
    finally:
        # PASSO 4: Remove arquivo temporário
        if os.path.exists(cleaned_pdf_path):
            os.unlink(cleaned_pdf_path)
            print(f"[Cleanup] Arquivo temporário removido")
    
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))