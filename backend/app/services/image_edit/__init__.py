"""User-driven image editing on top of nano-banana-pro.

Two flows the rest of the app calls:

  - inpaint_image(): regenerate ONLY a region the user highlighted on an
    existing generated image. Compositing the highlight into the source as
    a vivid magenta overlay turns out to be the most reliable way to point
    Gemini at "the part to change" — it doesn't have a native mask API but
    treats high-saturation overlay pixels as an obvious instruction.

  - sketch_to_image(): condition a fresh generation on a rough Excalidraw-
    style sketch the user drew. The sketch defines layout + key shapes;
    the prompt and brand fill in the rest.

Both reuse the brand snapshot pattern from frame_gen so edits inherit the
same palette/treatment as the original keyframes.
"""

from app.services.image_edit.edit import (
    decode_data_url,
    inpaint_image,
    sketch_to_image,
)

__all__ = ["inpaint_image", "sketch_to_image", "decode_data_url"]
