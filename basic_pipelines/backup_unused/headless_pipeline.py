"""
Pipeline GStreamer headless per rilevamento gatti.
"""

from detection_pipeline import GStreamerDetectionApp
from hailo_rpi_common import (
    SOURCE_PIPELINE,
    INFERENCE_PIPELINE,
    QUEUE,
    USER_CALLBACK_PIPELINE,
)

class HeadlessGStreamerApp(GStreamerDetectionApp):
    """
    Versione modificata di GStreamerDetectionApp per esecuzione headless
    """
    
    def __init__(self, callback_function, user_data, input_source=None, hef_path=None):
        """
        Inizializza l'applicazione headless.
        
        Args:
            callback_function: funzione di callback per il processamento dei frame
            user_data: dati utente per il callback
            input_source: sorgente video (e.g. /dev/video0)
            hef_path: percorso del file HEF
        """
        self.input_source = input_source
        self.hef_path = hef_path
        super().__init__(callback_function, user_data)
    
    def _create_pipeline(self):
        """
        Crea il pipeline GStreamer senza elementi di visualizzazione
        """
        arch = self._get_arch()
        pipeline_elements = []
        
        # Source pipeline (camera/video)
        source_string = SOURCE_PIPELINE(self.input_source)
        pipeline_elements.append(source_string)
        
        # Queue dopo la sorgente
        pipeline_elements.append(QUEUE("source_q"))
        
        # Pipeline di inferenza con Hailo
        inference_string = INFERENCE_PIPELINE(
            device_arch=arch,
            hef_path=self.hef_path,
            batch_size=2
        )
        pipeline_elements.append(inference_string)
        
        # Queue dopo l'inferenza
        pipeline_elements.append(QUEUE("inference_q"))
        
        # Pipeline callback utente
        callback_string = USER_CALLBACK_PIPELINE()
        pipeline_elements.append(callback_string)
        
        # Queue finale
        pipeline_elements.append(QUEUE("final_q"))
        
        # Sink fittizio (fakesink) per chiudere il pipeline
        pipeline_elements.append("fakesink sync=false")
        
        # Unisci tutti gli elementi
        return " ! ".join(pipeline_elements)

if __name__ == "__main__":
    print("This module should not be run directly")
