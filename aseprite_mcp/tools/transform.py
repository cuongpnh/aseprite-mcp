import os
from ..core.commands import AsepriteCommand, lua_escape
from ..core.lua import FIND_LAYER
from .. import mcp


@mcp.tool()
async def flip_layer(
    filename: str,
    layer_name: str,
    frame_index: int,
    direction: str = "horizontal",
) -> str:
    """Flip a layer's image horizontally or vertically.

    Args:
        filename: Aseprite file to modify
        layer_name: Layer name to flip
        frame_index: Frame index starting at 1
        direction: "horizontal" or "vertical"
    """
    if not os.path.exists(filename):
        return f"File {filename} not found"
    if direction not in ("horizontal", "vertical"):
        return "direction must be 'horizontal' or 'vertical'"

    safe_layer = lua_escape(layer_name)
    flip_h = "true" if direction == "horizontal" else "false"

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then print("ERROR:Frame index out of range") return end

    {FIND_LAYER}
    local target = find_layer(spr, "{safe_layer}")
    if not target then print("ERROR:Layer not found") return end

    local cel = target:cel(spr.frames[idx])
    if not cel then print("ERROR:No cel at that layer/frame") return end

    app.transaction(function()
        local img = cel.image
        local w = img.width
        local h = img.height
        local flip_horizontal = {flip_h}

        local pixels = {{}}
        for py = 0, h - 1 do
            pixels[py] = {{}}
            for px = 0, w - 1 do
                pixels[py][px] = img:getPixel(px, py)
            end
        end

        for py = 0, h - 1 do
            for px = 0, w - 1 do
                if flip_horizontal then
                    img:putPixel(px, py, pixels[py][w - 1 - px])
                else
                    img:putPixel(px, py, pixels[h - 1 - py][px])
                end
            end
        end
    end)

    spr:saveAs(spr.filename)
    print("OK")
    """

    success, output = AsepriteCommand.execute_lua_script_checked(script, filename)
    if success:
        return f"Layer '{layer_name}' flipped {direction}ly in {filename}"
    return f"Failed to flip layer: {output}"


# RotSprite-style rotation by any angle, for pixel art: the drawn box is enlarged 8x with Scale2x three times (rounding diagonals and
# keeping outlines whole), turned there about the pivot, and read back one pixel per 8x8 cell at its centre. Colours are never mixed:
# every pixel out was a pixel in. Aseprite's scripted Rotate command only takes quarter turns, and its free-angle RotSprite exists only
# in the interactive transform, so this does it in Lua. The same steps as gotchi-galaxy's render/rotSprite.ts, so a frame rotated here
# and one the game turns land on the same pixels when the pivot matches.
ROTSPRITE_LUA = """
local function rotsprite(img, deg, pivx, pivy, ox, oy, sw, sh)
    -- img: the cel's image at sprite offset (ox, oy); returns a sprite-sized image
    local w, h = img.width, img.height
    local x0, y0, x1, y1 = w, h, -1, -1
    local src = {}
    for y = 0, h - 1 do
        for x = 0, w - 1 do
            local v = img:getPixel(x, y)
            if app.pixelColor.rgbaA(v) == 0 then v = 0 end
            src[y * w + x] = v
            if v ~= 0 then
                if x < x0 then x0 = x end
                if y < y0 then y0 = y end
                if x > x1 then x1 = x end
                if y > y1 then y1 = y end
            end
        end
    end
    local out = Image(sw, sh, img.colorMode)
    if x1 < 0 then return out end
    local bx, by = math.max(0, x0 - 1), math.max(0, y0 - 1)
    local bw, bh = math.min(w - 1, x1 + 1) - bx + 1, math.min(h - 1, y1 + 1) - by + 1
    local big = {}
    for y = 0, bh - 1 do for x = 0, bw - 1 do big[y * bw + x] = src[(by + y) * w + bx + x] end end
    local cw, ch = bw, bh
    for _ = 1, 3 do
        local W = cw * 2
        local nb = {}
        for y = 0, ch - 1 do
            for x = 0, cw - 1 do
                local p = big[y * cw + x]
                local a = y > 0 and big[(y - 1) * cw + x] or p
                local b = x < cw - 1 and big[y * cw + x + 1] or p
                local c = x > 0 and big[y * cw + x - 1] or p
                local d = y < ch - 1 and big[(y + 1) * cw + x] or p
                local o = y * 2 * W + x * 2
                nb[o] = (c == a and c ~= d and a ~= b) and a or p
                nb[o + 1] = (a == b and a ~= c and b ~= d) and b or p
                nb[o + W] = (d == c and d ~= b and c ~= a) and c or p
                nb[o + W + 1] = (b == d and b ~= a and d ~= c) and d or p
            end
        end
        big = nb
        cw, ch = cw * 2, ch * 2
    end
    local r = math.rad(deg)
    local cs, sn = math.cos(r), math.sin(r)
    -- the pivot in the image's own pixels
    local cx, cy = pivx - ox, pivy - oy
    for sy = 0, sh - 1 do
        for sx = 0, sw - 1 do
            local dx, dy = sx - ox + 0.5 - cx, sy - oy + 0.5 - cy
            local ix, iy = cs * dx + sn * dy + cx, -sn * dx + cs * dy + cy
            local px, py = math.floor((ix - bx) * 8), math.floor((iy - by) * 8)
            if px >= 0 and py >= 0 and px < cw and py < ch then
                local v = big[py * cw + px]
                if v ~= 0 then out:putPixel(sx, sy, v) end
            end
        end
    end
    return out
end
"""


@mcp.tool()
async def rotate_layer(
    filename: str,
    layer_name: str,
    frame_index: int,
    angle: int = 90,
    pivot_x: float | None = None,
    pivot_y: float | None = None,
) -> str:
    """Rotate a layer's image clockwise. 90, 180 and 270 are exact quarter turns of the cel image; any other angle (e.g. 30, 45, -15)
    turns it the pixel-art way (RotSprite: Scale2x three times, rotate, read back at cell centres), so it stays crisp and uses only
    the colours already there.

    Args:
        filename: Aseprite file to modify
        layer_name: Layer name to rotate
        frame_index: Frame index starting at 1
        angle: Degrees clockwise; 90, 180, 270 are quarter turns, anything else is a free-angle RotSprite turn
        pivot_x: For a free angle: the point to turn about, sprite pixels (a pixel corner is a whole number); default the centre of
            the drawn pixels' box
        pivot_y: As pivot_x, vertical
    """
    if not os.path.exists(filename):
        return f"File {filename} not found"

    safe_layer = lua_escape(layer_name)
    if angle % 360 == 0:
        return f"Layer '{layer_name}' unchanged (0 degrees)"
    if angle % 90 != 0:
        px = "nil" if pivot_x is None else repr(float(pivot_x))
        py = "nil" if pivot_y is None else repr(float(pivot_y))
        script = f"""
    {ROTSPRITE_LUA}
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end
    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then print("ERROR:Frame index out of range") return end
    {FIND_LAYER}
    local target = find_layer(spr, "{safe_layer}")
    if not target then print("ERROR:Layer not found") return end
    local cel = target:cel(spr.frames[idx])
    if not cel then print("ERROR:No cel at that layer/frame") return end
    local img = cel.image
    local pivx, pivy = {px}, {py}
    if not pivx or not pivy then
        local b = img:shrinkBounds()
        if b.width == 0 then print("ERROR:The cel is empty") return end
        pivx = pivx or (cel.position.x + b.x + b.width / 2)
        pivy = pivy or (cel.position.y + b.y + b.height / 2)
    end
    app.transaction(function()
        local out = rotsprite(img, {float(angle)}, pivx, pivy, cel.position.x, cel.position.y, spr.width, spr.height)
        cel.image = out
        cel.position = Point(0, 0)
    end)
    spr:saveAs(spr.filename)
    print("OK " .. pivx .. "," .. pivy)
    """
        success, output = AsepriteCommand.execute_lua_script_checked(script, filename)
        if success:
            return f"Layer '{layer_name}' rotated {angle}° clockwise (RotSprite) in {filename}: {output.strip()}"
        return f"Failed to rotate layer: {output}"
    angle = angle % 360

    if angle == 180:
        rotate_lua = """
        local w = img.width
        local h = img.height
        local pixels = {}
        for py = 0, h - 1 do
            pixels[py] = {}
            for px = 0, w - 1 do
                pixels[py][px] = img:getPixel(px, py)
            end
        end
        for py = 0, h - 1 do
            for px = 0, w - 1 do
                img:putPixel(px, py, pixels[h - 1 - py][w - 1 - px])
            end
        end
        """
    elif angle == 90:
        # 90° clockwise: (px, py) → (old_h-1-py, px) in new image (new_w=old_h, new_h=old_w)
        rotate_lua = """
        local old_w = img.width
        local old_h = img.height
        local new_img = Image(old_h, old_w, img.colorMode)
        for py = 0, old_h - 1 do
            for px = 0, old_w - 1 do
                new_img:putPixel(old_h - 1 - py, px, img:getPixel(px, py))
            end
        end
        cel.image = new_img
        """
    else:
        # 270° clockwise (= 90° CCW): (px, py) → (py, old_w-1-px) in new image (new_w=old_h, new_h=old_w)
        rotate_lua = """
        local old_w = img.width
        local old_h = img.height
        local new_img = Image(old_h, old_w, img.colorMode)
        for py = 0, old_h - 1 do
            for px = 0, old_w - 1 do
                new_img:putPixel(py, old_w - 1 - px, img:getPixel(px, py))
            end
        end
        cel.image = new_img
        """

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then print("ERROR:Frame index out of range") return end

    {FIND_LAYER}
    local target = find_layer(spr, "{safe_layer}")
    if not target then print("ERROR:Layer not found") return end

    local cel = target:cel(spr.frames[idx])
    if not cel then print("ERROR:No cel at that layer/frame") return end

    app.transaction(function()
        local img = cel.image
        {rotate_lua}
    end)

    spr:saveAs(spr.filename)
    print("OK")
    """

    success, output = AsepriteCommand.execute_lua_script_checked(script, filename)
    if success:
        return f"Layer '{layer_name}' rotated {angle}° clockwise in {filename}"
    return f"Failed to rotate layer: {output}"


@mcp.tool()
async def resize_canvas(filename: str, width: int, height: int) -> str:
    """Scale the canvas and all its content to new dimensions.

    Args:
        filename: Aseprite file to modify
        width: New canvas width in pixels
        height: New canvas height in pixels
    """
    if not os.path.exists(filename):
        return f"File {filename} not found"
    if width <= 0 or height <= 0:
        return "Width and height must be > 0"

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    app.transaction(function()
        spr:resize({width}, {height})
    end)

    spr:saveAs(spr.filename)
    print("OK")
    """

    success, output = AsepriteCommand.execute_lua_script_checked(script, filename)
    if success:
        return f"Canvas resized to {width}x{height} in {filename}"
    return f"Failed to resize canvas: {output}"


@mcp.tool()
async def crop_canvas(filename: str, x: int, y: int, width: int, height: int) -> str:
    """Crop the canvas to the given rectangle, discarding content outside it.

    Args:
        filename: Aseprite file to modify
        x: Left edge of the crop area
        y: Top edge of the crop area
        width: Width of the crop area
        height: Height of the crop area
    """
    if not os.path.exists(filename):
        return f"File {filename} not found"
    if width <= 0 or height <= 0:
        return "Width and height must be > 0"

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    if {x} >= spr.width or {y} >= spr.height or {x} + {width} <= 0 or {y} + {height} <= 0 then
        print("ERROR:Crop rect is fully outside the canvas") return
    end

    app.transaction(function()
        spr:crop({x}, {y}, {width}, {height})
    end)

    spr:saveAs(spr.filename)
    print("OK")
    """

    success, output = AsepriteCommand.execute_lua_script_checked(script, filename)
    if success:
        return f"Canvas cropped to ({x},{y}) {width}x{height} in {filename}"
    return f"Failed to crop canvas: {output}"
