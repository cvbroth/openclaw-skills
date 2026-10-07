"""Make low-resolution visual layout indexes without running OCR."""
import argparse
from pathlib import Path
import fitz
from PIL import Image, ImageDraw

parser = argparse.ArgumentParser()
parser.add_argument('--pdf', type=Path, required=True)
parser.add_argument('--first-page', type=int, default=1)
parser.add_argument('--last-page', type=int, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
pdf = fitz.open(args.pdf)
if args.last_page > pdf.page_count or args.first_page < 1:
    raise SystemExit('page range outside PDF')
per_sheet, columns = 40, 5
thumb_width, margin, label_height = 180, 5, 22
for start in range(args.first_page, args.last_page + 1, per_sheet):
    pages = range(start, min(start + per_sheet, args.last_page + 1))
    rendered=[]
    for physical in pages:
        pix=pdf[physical-1].get_pixmap(matrix=fitz.Matrix(.18,.18),alpha=False,annots=False)
        img=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
        h=round(img.height*thumb_width/img.width)
        rendered.append((physical,img.resize((thumb_width,h))))
    rows=(len(rendered)+columns-1)//columns
    tile_height=max(x.height for _,x in rendered)+label_height
    sheet=Image.new('RGB',(columns*thumb_width,rows*tile_height),'white')
    draw=ImageDraw.Draw(sheet)
    for i,(physical,img) in enumerate(rendered):
        x = (i % columns) * thumb_width
        y = (i // columns) * tile_height
        draw.text((x+3,y+3),f'Physical {physical}',fill='black')
        sheet.paste(img,(x,y+label_height))
    path=args.output/f'pages-{start}-{min(start+per_sheet-1,args.last_page)}.png'
    sheet.save(path)
    print(path.name,path.stat().st_size)
