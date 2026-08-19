import tkinter as tk

from PIL import Image, ImageTk

from d2rlootreader.screen import capture_screen

# Constants for Tkinter window and drawing
OUTLINE_COLOR = "red"
OUTLINE_WIDTH = 2


class RegionSelectionApp:
    def __init__(self, master):
        self.master = master
        self.start_x = 0
        self.start_y = 0
        self.end_x = 0
        self.end_y = 0
        self.rect_id = None

        # Capture the screen before the Tkinter window appears
        self.original_screenshot_np = capture_screen()
        # Convert BGR (OpenCV default) to RGB for PIL
        self.original_screenshot_pil = Image.fromarray(self.original_screenshot_np[:, :, ::-1])
        self.tk_image = ImageTk.PhotoImage(self.original_screenshot_pil)

        master.attributes("-fullscreen", True)
        master.attributes("-topmost", True)

        self.canvas = tk.Canvas(master, cursor="cross")
        self.canvas.pack(fill="both", expand=True)

        # Display the screenshot on the canvas
        self.canvas.create_image(0, 0, image=self.tk_image, anchor="nw")

        self.canvas.bind("<ButtonPress-1>", self.on_mouse_press)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_release)

    def on_mouse_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y, outline=OUTLINE_COLOR, width=OUTLINE_WIDTH
        )

    def on_mouse_drag(self, event):
        self.end_x = event.x
        self.end_y = event.y
        self.canvas.coords(self.rect_id, self.start_x, self.start_y, self.end_x, self.end_y)

    def on_mouse_release(self, event):
        self.end_x = event.x
        self.end_y = event.y
        self.master.quit()

    def get_selected_image(self):
        x1 = min(self.start_x, self.end_x)
        y1 = min(self.start_y, self.end_y)
        x2 = max(self.start_x, self.end_x)
        y2 = max(self.start_y, self.end_y)

        # Crop the original numpy array screenshot
        cropped_image_np = self.original_screenshot_np[y1:y2, x1:x2]
        return cropped_image_np


def select_region():
    """
    Creates a full-screen Tkinter window with a static screenshot background
    to allow the user to select a region of the screen.
    The selected region is returned as a numpy array image.

    Returns:
        numpy.ndarray: The captured image in BGR format for the selected region.
    """
    root = tk.Tk()
    app = RegionSelectionApp(root)
    root.mainloop()
    root.destroy()
    return app.get_selected_image()
