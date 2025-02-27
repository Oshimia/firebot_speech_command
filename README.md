A Python program that will use a free Google API to listen for a trigger word and transcribe the following command to a text file. Will then trigger a URL call so that the transcription can be processed by another program. You will need to add the URL you want to call to the config file.

Designed for use with Firebot, so has a built in termination command to stop it running silently in the background, but this can be switched off in the config file. 

Has the option to instead use the OpenAi Whisper transcribe model for better accuracy of the command, but will still use the free google model to detect trigger words so as to avoid unnecessary costs, just add your API key to the config file. 

Has GUI to manage the program and update the config file without haveing to know any code. 
