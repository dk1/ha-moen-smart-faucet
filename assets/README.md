`icon.svg` is the source for `custom_components/moen_smart_faucet/brand/icon*.png`
(256 and 512 px). It's an original mark, not Moen's logo. To re-render:

```bash
pip install resvg-py pillow
python -c "import io,resvg_py;from PIL import Image;s=open('assets/icon.svg').read();[Image.open(io.BytesIO(bytes(resvg_py.svg_to_bytes(svg_string=s,width=n,height=n)))).save(f'custom_components/moen_smart_faucet/brand/{f}',optimize=True) for f,n in (('icon.png',256),('icon@2x.png',512))]"
```
