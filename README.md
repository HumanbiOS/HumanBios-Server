# HumanBios Server

## Prerequisites
`docker`, `docker-compose`, `python3.7`|`python3.8+`  
Make sure to create docker network for the containers
`docker network create caddynet`  

## Production
#### Get code
```
$ git clone git@github.com:HumanbiOS/HumanBios-Server.git
```
or
```
$ git clone https://github.com/HumanbiOS/HumanBios-Server.git
```
#### Update submodules
```
$ git submodule update --init --recursive
```
#### Setup .env
```
$ cp .env.example .env  
```
**Fill `.env`**  
#### Build container
```
$ docker build -t humanbios-server .
```
#### Database
Pull database image
```
$ docker pull amazon/dynamodb-local
```
Run database image
```
$ cd docker/db
$ docker-compose up -d
```
#### Run server
```
$ cd ..
$ docker-compose up -d
```

## Development (Not Dokerized)
#### Get code
```
$ git clone git@github.com:HumanbiOS/HumanBios-Server.git
```
or
```
$ git clone https://github.com/HumanbiOS/HumanBios-Server.git
```
#### Update submodules
```
$ git submodule update --init --recursive
```
#### Setup .env
```
$ cp .env.example .env  
```
**Fill `.env`**  
#### Database
Pull database image
```
$ docker pull amazon/dynamodb-local
```
Run database image
```
$ cd docker/db
$ docker-compose up -d
```
#### Setup Python / Run server
(return to the root dir of the project)
```
$ cd ../..
```
**Note: in the following section alias `python` is used for `python3`. Change it accordingly to your python (Windows `py`, Linux `python3` etc)**  
upgrade pip
```
$ python -m pip install --upgrade pip
```
install utils
```
$ python -m pip install --upgrade virtualenv wheel
```
setup python
```
$ python -m venv .venv
$ source .venv/bin/activate
$ python -m pip install -r requirements.txt
```
start app
```
$ python server.py
```

## Update
#### Update submodules
`$ git submodule foreach git pull origin master`
#### Else
**Note: currently front ends names and tokens are kept in memory, so when you reload server or front end instance, you need to restart everything**
