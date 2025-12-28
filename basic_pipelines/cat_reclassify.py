import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import os
import json
import shutil
from datetime import datetime

class CatReclassifyApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Cat Reclassification Tool")
        self.root.minsize(800, 600)

        # Directory paths
        self.named_cats_dir = "named_cats"
        self.dataset_dir = "dataset"
        self.train_dir = os.path.join(self.dataset_dir, "train")
        self.val_dir = os.path.join(self.dataset_dir, "val")
        self.test_dir = os.path.join(self.dataset_dir, "test")
        
        # Load database
        self.db_file = "cats_database.json"
        self.load_database()
        
        # Create GUI
        self.create_widgets()
        
        # Load initial data
        self.load_cat_images()

    def load_database(self):
        if os.path.exists(self.db_file):
            with open(self.db_file, 'r') as f:
                self.cats_db = json.load(f)
        else:
            messagebox.showerror("Error", "Database file not found!")
            self.cats_db = {}

    def save_database(self):
        with open(self.db_file, 'w') as f:
            json.dump(self.cats_db, f, indent=4)

    def create_widgets(self):
        # Main container
        main_container = ttk.Frame(self.root, padding="10")
        main_container.pack(fill=tk.BOTH, expand=True)

        # Left panel for image and controls
        left_panel = ttk.Frame(main_container)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Image display
        self.image_frame = ttk.Frame(left_panel, relief="solid", borderwidth=1)
        self.image_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        self.image_label = ttk.Label(self.image_frame)
        self.image_label.pack(pady=10, padx=10)

        # Image info
        self.info_label = ttk.Label(left_panel, font=('Helvetica', 10))
        self.info_label.pack(pady=5)

        # Controls for reclassification
        controls_frame = ttk.LabelFrame(left_panel, text="Reclassification Controls", padding="5")
        controls_frame.pack(fill=tk.X, pady=10)

        # Current cat name and split
        current_info = ttk.Frame(controls_frame)
        current_info.pack(fill=tk.X, pady=5)
        ttk.Label(current_info, text="Current Cat:").pack(side=tk.LEFT, padx=5)
        self.current_cat_label = ttk.Label(current_info, font=('Helvetica', 10, 'bold'))
        self.current_cat_label.pack(side=tk.LEFT, padx=5)
        ttk.Label(current_info, text="Current Split:").pack(side=tk.LEFT, padx=5)
        self.current_split_label = ttk.Label(current_info, font=('Helvetica', 10, 'bold'))
        self.current_split_label.pack(side=tk.LEFT, padx=5)

        # New classification controls
        new_class_frame = ttk.Frame(controls_frame)
        new_class_frame.pack(fill=tk.X, pady=5)
        
        # Cat selection
        ttk.Label(new_class_frame, text="New Cat:").pack(side=tk.LEFT, padx=5)
        self.cat_var = tk.StringVar()
        self.cat_combo = ttk.Combobox(new_class_frame, textvariable=self.cat_var)
        self.cat_combo['values'] = sorted(self.cats_db.keys())
        self.cat_combo.pack(side=tk.LEFT, padx=5)
        
        # Split selection
        ttk.Label(new_class_frame, text="New Split:").pack(side=tk.LEFT, padx=5)
        self.split_var = tk.StringVar(value="train")
        for split in ["train", "val", "test"]:
            ttk.Radiobutton(new_class_frame, text=split.capitalize(), 
                          variable=self.split_var, value=split).pack(side=tk.LEFT, padx=5)

        # Action buttons
        button_frame = ttk.Frame(left_panel)
        button_frame.pack(fill=tk.X, pady=10)
        
        ttk.Button(button_frame, text="← Previous", 
                  command=self.previous_image).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Save Changes", 
                  command=self.save_changes).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Next →", 
                  command=self.next_image).pack(side=tk.LEFT, padx=5)

        # Navigation frame
        nav_frame = ttk.LabelFrame(left_panel, text="Navigation", padding="5")
        nav_frame.pack(fill=tk.X, pady=10)
        
        # Cat filter
        ttk.Label(nav_frame, text="Filter by Cat:").pack(side=tk.LEFT, padx=5)
        self.filter_var = tk.StringVar()
        filter_combo = ttk.Combobox(nav_frame, textvariable=self.filter_var)
        filter_combo['values'] = ["All"] + sorted(self.cats_db.keys())
        filter_combo.set("All")
        filter_combo.pack(side=tk.LEFT, padx=5)
        filter_combo.bind('<<ComboboxSelected>>', self.apply_filter)

    def load_cat_images(self):
        self.images = []
        self.current_index = 0
        
        # Get all images from named_cats directory
        for cat_name, entries in self.cats_db.items():
            if self.filter_var.get() == "All" or self.filter_var.get() == cat_name:
                for entry in entries:
                    filename = entry['new_filename']
                    if os.path.exists(os.path.join(self.named_cats_dir, filename)):
                        self.images.append({
                            'filename': filename,
                            'cat_name': cat_name,
                            'split': entry.get('split', 'train')  # default to train if not specified
                        })
        
        if self.images:
            self.display_current_image()
        else:
            self.image_label.config(image='')
            self.info_label.config(text="No images found")

    def display_current_image(self):
        if 0 <= self.current_index < len(self.images):
            image_info = self.images[self.current_index]
            image_path = os.path.join(self.named_cats_dir, image_info['filename'])
            
            # Load and display image
            image = Image.open(image_path)
            display_size = (500, 400)
            image.thumbnail(display_size, Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            self.image_label.config(image=photo)
            self.image_label.image = photo
            
            # Update info labels
            self.info_label.config(text=f"Image {self.current_index + 1} of {len(self.images)}")
            self.current_cat_label.config(text=image_info['cat_name'])
            self.current_split_label.config(text=image_info['split'])
            
            # Pre-select current values in controls
            self.cat_var.set(image_info['cat_name'])
            self.split_var.set(image_info['split'])

    def apply_filter(self, event=None):
        self.load_cat_images()

    def previous_image(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.display_current_image()

    def next_image(self):
        if self.current_index < len(self.images) - 1:
            self.current_index += 1
            self.display_current_image()

    def save_changes(self):
        if not self.images:
            return
            
        current_image = self.images[self.current_index]
        old_cat = current_image['cat_name']
        new_cat = self.cat_var.get()
        new_split = self.split_var.get()
        
        if not new_cat:
            messagebox.showwarning("Input Required", "Please select a cat name.")
            return
            
        # Find the entry in the database
        original_entry = None
        for entry in self.cats_db[old_cat]:
            if entry['new_filename'] == current_image['filename']:
                original_entry = entry
                break
                
        if original_entry:
            # Remove from old cat's entries
            self.cats_db[old_cat].remove(original_entry)
            
            # Add to new cat's entries
            if new_cat not in self.cats_db:
                self.cats_db[new_cat] = []
            
            # Create new entry
            new_entry = original_entry.copy()
            new_entry['split'] = new_split
            
            # If cat name changed, create new filename
            if old_cat != new_cat:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                old_path = os.path.join(self.named_cats_dir, original_entry['new_filename'])
                new_filename = f"{new_cat}_{timestamp}.jpg"
                new_path = os.path.join(self.named_cats_dir, new_filename)
                
                # Move file in named_cats directory
                shutil.move(old_path, new_path)
                
                # Update entry
                new_entry['new_filename'] = new_filename
                new_entry['date_cataloged'] = timestamp
            
            self.cats_db[new_cat].append(new_entry)
            
            # Move file in dataset directory
            old_dataset_path = os.path.join(self.dataset_dir, current_image['split'], current_image['filename'])
            new_dataset_path = os.path.join(self.dataset_dir, new_split, new_entry['new_filename'])
            
            if os.path.exists(old_dataset_path):
                os.makedirs(os.path.dirname(new_dataset_path), exist_ok=True)
                shutil.copy2(os.path.join(self.named_cats_dir, new_entry['new_filename']), new_dataset_path)
                os.remove(old_dataset_path)
            
            # Save changes
            self.save_database()
            
            # Store current index
            current_position = self.current_index
            
            # Reload images while trying to maintain position
            old_length = len(self.images)
            self.load_cat_images()
            
            # Adjust index based on filter and changes
            if self.filter_var.get() != "All" and self.filter_var.get() != new_cat:
                # If we're filtering and the image was moved to a different cat,
                # remove it from view by moving to next image
                self.current_index = min(current_position, len(self.images) - 1)
            else:
                # Try to maintain the same position
                self.current_index = min(current_position, len(self.images) - 1)
            
            # Display the current image
            if self.images:
                self.display_current_image()
            
            messagebox.showinfo("Success", "Image reclassified successfully!")
        else:
            messagebox.showerror("Error", "Could not find image in database!")

if __name__ == "__main__":
    root = tk.Tk()
    app = CatReclassifyApp(root)
    root.mainloop()
