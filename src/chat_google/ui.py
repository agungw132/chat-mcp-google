import gradio as gr

from chat_google.chat_service import chat
from chat_google.constants import AVAILABLE_MODELS, DEFAULT_MODEL


def build_demo() -> gr.Blocks:
    with gr.Blocks(title="Sumopod AI Chat") as demo:
        gr.Markdown("# Sumopod AI Chat (Gmail, Calendar, Contacts)")

        chatbot = gr.Chatbot()

        with gr.Row():
            msg_input = gr.Textbox(placeholder="Ketik pesan di sini...", scale=9)
            retry_btn = gr.Button("Ulangi", scale=1)

        with gr.Row():
            model_dropdown = gr.Dropdown(
                choices=AVAILABLE_MODELS,
                value=DEFAULT_MODEL,
                label="Pilih Model",
                scale=8,
            )
            clear_btn = gr.Button("Bersihkan", scale=2)

        last_message = gr.State("")

        async def user_submit(message, history):
            new_history = history + [{"role": "user", "content": message}]
            return "", new_history, message

        async def bot_respond(history, model_name):
            user_msg = history[-1]["content"]
            async for updated_history in chat(user_msg, history[:-1], model_name):
                yield updated_history

        msg_input.submit(
            user_submit,
            [msg_input, chatbot],
            [msg_input, chatbot, last_message],
        ).then(
            bot_respond,
            [chatbot, model_dropdown],
            [chatbot],
        )

        retry_btn.click(
            lambda m: m,
            [last_message],
            [msg_input],
        ).then(
            user_submit,
            [msg_input, chatbot],
            [msg_input, chatbot, last_message],
        ).then(
            bot_respond,
            [chatbot, model_dropdown],
            [chatbot],
        )

        clear_btn.click(lambda: [], None, chatbot)

    return demo


def main() -> None:
    demo = build_demo()
    demo.launch()

