import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import os
import json
import shutil
from datetime import datetime

class EnhancedCatCatalogApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Enhanced Cat Catalog")
        
        # Set minimum window size
        self.root.minsize(800, 600)

        # Directory paths
        self.detected_cats_dir = "detected_cats"
        self.named_cats_dir = "named_cats"
        self.dataset_dir = "dataset"
        self.train_dir = os.path.join(self.dataset_dir, "train")
        self.val_dir = os.path.join(self.dataset_dir, "val")
        self.test_dir = os.path.join(self.dataset_dir, "test")
        
        # Create all necessary directories
        for directory in [self.detected_cats_dir, self.named_cats_dir, 
                         self.train_dir, self.val_dir, self.test_dir]:
            os.makedirs(directory, exist_ok=True)

        # Load or create cats database
        self.db_file = "cats_database.json"
        self.load_database()

        # Get list of uncataloged images
        self.image_files = [f for f in os.listdir(self.detected_cats_dir) 
                          if f.endswith(('.jpg', '.jpeg', '.png'))]
        self.current_image_index = 0

        # Create GUI elements
        self.create_widgets()

        # Load first image if available
        if self.image_files:
            self.load_current_image()

    def load_database(self):
        if os.path.exists(self.db_file):
            with open(self.db_file, 'r') as f:
                self.cats_db = json.load(f)
        else:
            self.cats_db = {}

    def save_database(self):
        with open(self.db_file, 'w') as f:
            json.dump(self.cats_db, f, indent=4)

    def create_quick_name_buttons(self, parent):
        """Create buttons for each unique cat name in the database"""
        # Distruggi il frame dei pulsanti precedente se esiste
        if hasattr(self, 'buttons_frame'):
            self.buttons_frame.destroy()
            
        self.buttons_frame = ttk.LabelFrame(parent, text="Quick Select Cat", padding="5")
        self.buttons_frame.pack(fill=tk.X, pady=5)

        # Get unique cat names and sort them
        cat_names = sorted(self.cats_db.keys())
        
        # Create a grid of buttons
        row = 0
        col = 0
        max_cols = 3  # Number of buttons per row
        
        for name in cat_names:
            btn = ttk.Button(self.buttons_frame, text=name, 
                           command=lambda n=name: self.set_cat_name(n))
            btn.grid(row=row, column=col, padx=5, pady=2, sticky='ew')
            
            col += 1
            if col >= max_cols:
                col = 0
                row += 1

        # Configure grid columns to be of equal width
        for i in range(max_cols):
            self.buttons_frame.grid_columnconfigure(i, weight=1)

    def set_cat_name(self, name):
        """Set the cat name in the entry field"""
        self.name_entry.delete(0, tk.END)
        self.name_entry.insert(0, name)

    def create_widgets(self):
        # Main container with padding
        main_container = ttk.Frame(self.root, padding="10")
        main_container.pack(fill=tk.BOTH, expand=True)

        # Left panel
        self.left_panel = ttk.Frame(main_container)
        self.left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Image frame with border
        image_frame = ttk.Frame(self.left_panel, relief="solid", borderwidth=1)
        image_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.image_label = ttk.Label(image_frame)
        self.image_label.pack(pady=10, padx=10)

        # File info with better styling
        self.file_info = ttk.Label(self.left_panel, font=('Helvetica', 10))
        self.file_info.pack(pady=(0, 10))

        # Quick name buttons
        self.create_quick_name_buttons(self.left_panel)

        # Entry frame with padding
        entry_frame = ttk.Frame(self.left_panel)
        entry_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(entry_frame, text="Cat's Name:", font=('Helvetica', 10, 'bold')).pack(side=tk.LEFT, padx=5)
        self.name_entry = ttk.Entry(entry_frame, width=30)
        self.name_entry.pack(side=tk.LEFT, padx=5)

        # Dataset split selector with padding and better layout
        split_frame = ttk.LabelFrame(self.left_panel, text="Dataset Split", padding="5")
        split_frame.pack(fill=tk.X, pady=10)
        
        self.split_var = tk.StringVar(value="train")
        for split in ["train", "val", "test"]:
            ttk.Radiobutton(split_frame, text=split.capitalize(), 
                          variable=self.split_var, value=split).pack(side=tk.LEFT, padx=20)

        # Button frame with proper spacing and styling
        button_frame = ttk.Frame(self.left_panel)
        button_frame.pack(fill=tk.X, pady=20)
        
        button_frame.grid_columnconfigure(0, weight=1)
        button_frame.grid_columnconfigure(1, weight=1)
        button_frame.grid_columnconfigure(2, weight=1)

        # Create styled buttons
        style = ttk.Style()
        style.configure('Action.TButton', font=('Helvetica', 10, 'bold'))
        
        ttk.Button(button_frame, text="← Previous", command=self.previous_image, 
                  style='Action.TButton').grid(row=0, column=0, padx=5, sticky='ew')
        ttk.Button(button_frame, text="Save", command=self.save_cat,
                  style='Action.TButton').grid(row=0, column=1, padx=5, sticky='ew')
        ttk.Button(button_frame, text="Next →", command=self.next_image,
                  style='Action.TButton').grid(row=0, column=2, padx=5, sticky='ew')

        # Progress label
        self.progress_label = ttk.Label(self.left_panel, font=('Helvetica', 9))
        self.progress_label.pack(pady=10)

        # Right panel with statistics
        right_panel = ttk.LabelFrame(main_container, text="Dataset Statistics", padding="10")
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(10, 0))

        self.stats_text = tk.Text(right_panel, width=30, height=20, font=('Courier', 9))
        self.stats_text.pack(pady=5)
        self.update_statistics()

    def update_statistics(self):
        self.stats_text.delete('1.0', tk.END)
        for cat_name in sorted(self.cats_db.keys()):
            entries = self.cats_db[cat_name]
            train = sum(1 for e in entries if e.get('split') == 'train')
            val = sum(1 for e in entries if e.get('split') == 'val')
            test = sum(1 for e in entries if e.get('split') == 'test')
            total = len(entries)
            
            self.stats_text.insert(tk.END, f"{cat_name}:\n")
            self.stats_text.insert(tk.END, f"  Train: {train}\n")
            self.stats_text.insert(tk.END, f"  Val:   {val}\n")
            self.stats_text.insert(tk.END, f"  Test:  {test}\n")
            self.stats_text.insert(tk.END, f"  Total: {total}\n\n")

    def load_current_image(self):
        if 0 <= self.current_image_index < len(self.image_files):
            # Update progress
            self.progress_label.config(
                text=f"Image {self.current_image_index + 1} of {len(self.image_files)}")
            
            # Load and display image
            image_path = os.path.join(self.detected_cats_dir, 
                                    self.image_files[self.current_image_index])
            image = Image.open(image_path)
            
            # Resize image while maintaining aspect ratio
            display_size = (500, 400)
            image.thumbnail(display_size, Image.Resampling.LANCZOS)
            
            photo = ImageTk.PhotoImage(image)
            self.image_label.config(image=photo)
            self.image_label.image = photo  # Keep a reference!

            # Update file info
            self.file_info.config(text=self.image_files[self.current_image_index])

    def next_image(self):
        if self.current_image_index < len(self.image_files) - 1:
            self.current_image_index += 1
            self.load_current_image()

    def previous_image(self):
        if self.current_image_index > 0:
            self.current_image_index -= 1
            self.load_current_image()

    def save_cat(self):
        if not self.image_files:
            return

        cat_name = self.name_entry.get().strip()
        if not cat_name:
            messagebox.showwarning("Input Required", "Please enter a name for the cat.")
            return

        current_file = self.image_files[self.current_image_index]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_filename = f"{cat_name}_{timestamp}.jpg"

        # Get selected split
        split = self.split_var.get()
        split_dir = getattr(self, f"{split}_dir")

        old_path = os.path.join(self.detected_cats_dir, current_file)
        
        # Verify file exists before copying/moving
        if not os.path.exists(old_path):
            messagebox.showerror("Error", f"Source file not found: {current_file}")
            return

        try:
            # Copy to dataset directory
            new_path = os.path.join(split_dir, new_filename)
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            shutil.copy2(old_path, new_path)

            # Also save to named_cats for reference
            os.makedirs(self.named_cats_dir, exist_ok=True)
            named_path = os.path.join(self.named_cats_dir, new_filename)
            shutil.move(old_path, named_path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save file: {str(e)}")
            return

        # Update database
        if cat_name not in self.cats_db:
            self.cats_db[cat_name] = []
        self.cats_db[cat_name].append({
            'original_filename': current_file,
            'new_filename': new_filename,
            'date_cataloged': timestamp,
            'split': split
        })
        self.save_database()
        
        # Refresh quick name buttons and statistics
        self.create_quick_name_buttons(self.left_panel)
        self.update_statistics()

        # Remove from list and update display
        self.image_files.pop(self.current_image_index)
        if self.image_files:
            if self.current_image_index >= len(self.image_files):
                self.current_image_index = len(self.image_files) - 1
            self.load_current_image()
        else:
            self.image_label.config(image='')
            self.file_info.config(text="No more images to catalog")
            self.progress_label.config(text="All images have been cataloged")

if __name__ == "__main__":
    root = tk.Tk()
    app = EnhancedCatCatalogApp(root)
    root.mainloop()
