FROM python:3.10

WORKDIR /app
 
COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY . .

CMD ["streamlit", "run", "frontend.py", "--server.port=8080", "--server.address=0.0.0.0"]