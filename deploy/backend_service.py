import json
import logging
import os
import os.path as osp
import pathlib
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import pytz
from flask import Flask, request, jsonify, Response
from mmcv import Config

ROOT = str(pathlib.Path(__file__).resolve().parents[1])
sys.path.append(ROOT)

from trademaster.utils import replace_cfg_vals, MRL_F2B_args_converter
from flask_cors import CORS
import os.path as osp
import pickle
import csv

from tools import market_dynamics_labeling
import base64

tz = pytz.timezone('Asia/Shanghai')

app = Flask(__name__)
CORS(app, resources={r"/TradeMaster/*": {"origins": "*"}})
def run_cmd(cmd):
    process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    command_output = process.stdout.read().decode('utf-8')
    return command_output


def get_logger():
    logger = logging.getLogger('server')
    logger.setLevel(logging.DEBUG)

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        '[%(asctime)s][%(thread)d][%(filename)s][line: %(lineno)d][%(levelname)s] ## %(message)s')
    ch.setFormatter(formatter)

    logger.addHandler(ch)

    return logger


logger = get_logger()
executor = ThreadPoolExecutor()


class Server():
    def __init__(self):
        self.logger = None
        self.sessions = self.load_sessions()

    def parameters(self):
        res = {
            "task_name": ["algorithmic_trading", "order_execution", "portfolio_management"],
            "dataset_name": [
                            "algorithmic_trading:BTC",
                            "algorithmic_trading:FX",
                             "algorithmic_trading:JPM",
                             "order_excecution:BTC",
                             "order_excecution:PD_BTC",
                             "portfolio_management:dj30",
                             "portfolio_management:exchange"],
            "optimizer_name": ["adam"],
            "loss_name": ["mse"],
            "agent_name": [
                "algorithmic_trading:deepscalper",
                "order_execution:eteo",
                "order_execution:pd",
                "portfolio_management:a2c",
                "portfolio_management:ddpg",
                "portfolio_management:eiie",
                "portfolio_management:investor_imitator",
                "portfolio_management:pg",
                "portfolio_management:ppo",
                "portfolio_management:sac",
                "portfolio_management:sarl",
                "portfolio_management:td3"
            ],
            "start_date": {
                "algorithmic_trading:BTC": "2015-10-01",
                "algorithmic_trading:FX": "2000-01-01",
                "order_excecution:BTC": "2021-04-07",
                "order_excecution:PD_BTC": "2013-04-29",
                "portfolio_management:dj30": "2012-01-04",
                "portfolio_management:exchange": "2000-01-27",
            },
            "end_date": {
                "algorithmic_trading:BTC": "2021-07-06",
                "algorithmic_trading:FX": "2019-12-31",
                "order_excecution:BTC": "2021-03-19",
                "order_excecution:PD_BTC": "2021-07-05",
                "portfolio_management:dj30": "2021-12-31",
                "portfolio_management:exchange": "2019-12-31",
            },
            "dynamics_test": [
                "bear_market",
                "bull_market",
                "oscillation_market"
            ]


        }
        return res

    def evaluation_parameters(self):
        res ={
            "start_date": {
                "algorithmic_trading:BTC": "2020-03-03",
                "algorithmic_trading:FX": "2017-12-22",
                "order_excecution:BTC": "2021-04-17",
                "order_excecution:PD_BTC": "2018-09-10",
                "portfolio_management:dj30": "2020-04-01",
                "portfolio_management:exchange": "2018-08-09",
            },
            "end_date": {
                "algorithmic_trading:BTC": "2021-07-05",
                "algorithmic_trading:FX": "2019-12-31",
                "order_excecution:BTC": "2021-04-19",
                "order_excecution:PD_BTC": "2021-07-05",
                "portfolio_management:dj30": "2021-12-31",
                "portfolio_management:exchange": "2019-12-31",
            },
            "number_of_market_style": ["3"],
            "length_time_slice": {
                "algorithmic_trading:BTC": "12",
                "algorithmic_trading:FX": "24",
                "order_excecution:BTC": "32",
                "order_excecution:PD_BTC": "32",
                "portfolio_management:dj30": "12",
                "portfolio_management:exchange": "12"
            },
            "bear_threshold": {
                "algorithmic_trading:BTC": "-0.4",
                "algorithmic_trading:FX": "-0.05",
                "order_excecution:BTC": "-0.01",
                "order_excecution:PD_BTC": "-0.3",
                "portfolio_management:dj30": "-0.15",
                "portfolio_management:exchange": "-0.03"
            },
            "bull_threshold": {
                "algorithmic_trading:BTC": "0.4",
                "algorithmic_trading:FX": "0.05",
                "order_excecution:BTC": "0.01",
                "order_excecution:PD_BTC": "0.3",
                "portfolio_management:dj30": "0.15",
                "portfolio_management:exchange": "0.03"
            }
        }
        return res

    def train_scripts(self, task_name, dataset_name, optimizer_name, loss_name, agent_name):
        if task_name == "algorithmic_trading":
            return os.path.join(ROOT, "tools", "algorithmic_trading", "train.py")
        elif task_name == "order_execution":
            if agent_name == "eteo":
                return os.path.join(ROOT, "tools", "order_execution", "train_eteo.py")
            elif agent_name == "pd":
                return os.path.join(ROOT, "tools", "order_execution", "train_pd.py")
        elif task_name == "portfolio_management":
            if dataset_name == "dj30":
                if agent_name == "deeptrader":
                    return os.path.join(ROOT, "tools", "portfolio_management", "train_deeptrader.py")
                elif agent_name == "eiie":
                    return os.path.join(ROOT, "tools", "portfolio_management", "train_eiie.py")
                elif agent_name == "investor_imitator":
                    return os.path.join(ROOT, "tools", "portfolio_management", "train_investor_imitator.py")
                elif agent_name == "sarl":
                    return os.path.join(ROOT, "tools", "portfolio_management", "train_sarl.py")
            elif dataset_name == "exchange":
                return os.path.join(ROOT, "tools", "portfolio_management", "train.py")
        elif task_name == 'market_dynamics_modeling':
            return os.path.join(ROOT, "tools", "market_dynamics_labeling", "run.py")

    def load_sessions(self):
        if os.path.exists("session.json"):
            with open("session.json", "r") as op:
                sessions = json.load(op)
        else:
            self.dump_sessions({})
            sessions = {}

        return sessions

    def dump_sessions(self, data):
        if os.path.exists("session.json"):
            with open("session.json", "r") as op:
                sessions = json.load(op)
        else:
            sessions = {}
        sessions.update(data)

        with open("session.json", "w") as op:
            json.dump(sessions, op)
        return sessions

    def get_parameters(self, request):
        logger.info("get parameters start.")
        param = self.parameters()
        logger.info("get parameters end.")
        return jsonify(param)

    def train(self, request):
        request_json = json.loads(request.get_data(as_text=True))
        try:
            task_name = request_json.get("task_name")
            dataset_name = request_json.get("dataset_name").split(":")[-1]
            optimizer_name = request_json.get("optimizer_name")
            loss_name = request_json.get("loss_name")
            agent_name = request_json.get("agent_name").split(":")[-1]
            try:
                start_date = request_json.get("start_date")
            except:
                start_date = None
            try:
                end_date = request_json.get("end_date")
            except:
                end_date = None
            ##TODO
            session_id = str(uuid.uuid1())

            cfg_path = os.path.join(ROOT, "configs", task_name,
                                    f"{task_name}_{dataset_name}_{agent_name}_{agent_name}_{optimizer_name}_{loss_name}.py")
            train_script_path = self.train_scripts(task_name, dataset_name, optimizer_name, loss_name, agent_name)
            work_dir = os.path.join(ROOT, "work_dir", session_id,
                                    f"{task_name}_{dataset_name}_{agent_name}_{agent_name}_{optimizer_name}_{loss_name}")
            if not os.path.exists(work_dir):
                os.makedirs(work_dir)

            cfg = Config.fromfile(cfg_path)
            cfg = replace_cfg_vals(cfg)
            cfg.work_dir = "work_dir/{}/{}".format(session_id,
                                                   f"{task_name}_{dataset_name}_{agent_name}_{agent_name}_{optimizer_name}_{loss_name}")
            cfg.trainer.work_dir = cfg.work_dir

            # build dataset

            if not start_date or not end_date or (task_name == "algorithmic_trading" and dataset_name == "BTC"):
                train_data = pd.read_csv(os.path.join(ROOT, cfg.data.data_path, "train.csv"), index_col=0)
                val_data = pd.read_csv(os.path.join(ROOT, cfg.data.data_path, "valid.csv"), index_col=0)
                test_data = pd.read_csv(os.path.join(ROOT, cfg.data.data_path, "test.csv"), index_col=0)

            else :
                data = pd.read_csv(os.path.join(ROOT, cfg.data.data_path, "data.csv"), index_col=0)
                data = data[(data["date"] >= start_date) & (data["date"] < end_date)]

                # indexs = range(len(data.index.unique()))
                indexs = data.index.unique()

                train_indexs = indexs[:int(len(indexs) * 0.8)]
                val_indexs = indexs[int(len(indexs) * 0.8):int(len(indexs) * 0.9)]
                test_indexs = indexs[int(len(indexs) * 0.9):]

                train_data = data.loc[train_indexs, :]
                train_data.index = train_data.index - train_data.index.min()

                val_data = data.loc[val_indexs, :]
                val_data.index = val_data.index - val_data.index.min()

                test_data = data.loc[test_indexs, :]
                test_data.index = test_data.index - test_data.index.min()



            train_data.to_csv(os.path.join(work_dir, "train.csv"))
            cfg.data.train_path = "{}/{}".format(cfg.work_dir, "train.csv")
            val_data.to_csv(os.path.join(work_dir, "valid.csv"))
            cfg.data.valid_path = "{}/{}".format(cfg.work_dir, "valid.csv")
            test_data.to_csv(os.path.join(work_dir, "test.csv"))
            cfg.data.test_path = "{}/{}".format(cfg.work_dir, "test.csv")

            cfg_path = os.path.join(work_dir, osp.basename(cfg_path))
            cfg.dump(cfg_path)
            logger.info(cfg)

            log_path = os.path.join(work_dir, "train_log.txt")

            self.sessions = self.dump_sessions({session_id: {
                "dataset":request_json.get("dataset_name"),
                "task_name": task_name,
                "work_dir": work_dir,
                "cfg_path": cfg_path,
                "script_path": train_script_path,
                "train_log_path": log_path,
                "test_log_path": os.path.join(os.path.dirname(log_path), "test_log.txt")
            }})

            cmd = "conda activate TradeMaster && nohup python -u {} --config {} --task_name train --verbose 0 > {} 2>&1 &".format(
                train_script_path,
                cfg_path,
                log_path)

            executor.submit(run_cmd, cmd)
            logger.info(cmd)

            error_code = 0
            info = "request success, start train"
            res = {
                "error_code": error_code,
                "info": info,
                "session_id": session_id
            }
            logger.info(info)
            return jsonify(res)

        except Exception as e:
            error_code = 1
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            info = "request data error, {}".format(e)
            print(info)
            res = {
                "error_code": error_code,
                "info": info+str(exc_type) + str(fname) + str(exc_tb.tb_lineno),
                "session_id": ""
            }
            return jsonify(res)

    def train_status(self, request):
        request_json = json.loads(request.get_data(as_text=True))
        try:

            self.sessions = self.load_sessions()
            session_id = request_json.get("session_id")
            work_dir = self.sessions[session_id]["work_dir"]


            if session_id in self.sessions:
                if os.path.exists(self.sessions[session_id]["train_log_path"]):
                    cmd = "tail -n 2000 {}".format(self.sessions[session_id]["train_log_path"])
                    info = run_cmd(cmd)
                else:
                    info = ""
            else:
                info = "waitinig for train start"
            if 'train end' in info:
                train_end = True
                with open(osp.join(work_dir, f"Visualization_valid.png"), "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read())
                    result_plot = str(encoded_string, 'utf-8')
            else:
                train_end = False
                result_plot = None

            # parse every line of info with 'm ' and get the latter part
            info = [line.split('m ')[-1] if 'm ' in line else line for line in info.split('\n')]
            # remove 'nohup: ignoring input' in info
            info = [line for line in info if 'nohup: ignoring input' not in line]
            info = '\n'.join(info)


            res = {
                "info": info,
                "train_end": train_end,
                'result_plot': result_plot
            }
            logger.info("get train status success")
            return jsonify(res)

        except Exception as e:
            error_code = 1
            info = "request data error, {}".format(e)
            res = {
                "error_code": error_code,
                "info": '',
                "session_id": ""
            }
            logger.info(info)
            return jsonify(res)

    def test(self, request):
        request_json = json.loads(request.get_data(as_text=True))
        try:

            self.sessions = self.load_sessions()
            session_id = request_json.get("session_id")

            work_dir = self.sessions[session_id]["work_dir"]
            script_path = self.sessions[session_id]["script_path"]
            cfg_path = self.sessions[session_id]["cfg_path"]
            log_path = self.sessions[session_id]["test_log_path"]

            cmd = "conda activate TradeMaster && nohup python -u {} --config {} --task_name test --verbose 0 > {} 2>&1 &".format(
                script_path,
                cfg_path,
                log_path)
            executor.submit(run_cmd, cmd)
            logger.info(cmd)

            error_code = 0
            info = "request success, start test"
            res = {
                "error_code": error_code,
                "info": info,
                "session_id": session_id
            }
            logger.info(info)
            return jsonify(res)

        except Exception as e:
            error_code = 1
            info = "request data error, {}".format(e)
            res = {
                "error_code": error_code,
                "info": info,
                "session_id": ""
            }
            logger.info(info)
            return jsonify(res)

    def test_status(self, request):
        request_json = json.loads(request.get_data(as_text=True))
        try:
            self.sessions = self.load_sessions()
            session_id = request_json.get("session_id")
            work_dir = self.sessions[session_id]["work_dir"]
            if session_id in self.sessions:
                cmd = "tail -n 2000 {}".format(self.sessions[session_id]["test_log_path"])
                info = run_cmd(cmd)
            else:
                info = 'waiting for test start'

            if 'test end' in info:
                test_end = True
                with open(osp.join(work_dir, f"Visualization_test.png"), "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read())
                result_plot = str(encoded_string, 'utf-8')
            else:
                test_end = False
                result_plot = None

            # parse every line of info with 'm ' and get the latter part if 'm ' in line else keep the line
            info = [line.split('m ')[-1] if 'm ' in line else line for line in info.split('\n')]
            info = [line for line in info if 'nohup: ignoring input' not in line]
            info = '\n'.join(info)

            res = {
                "info": info,
                "test_end": test_end,
                'result_plot': result_plot
            }
            logger.info("get train status success")
            return jsonify(res)

        except Exception as e:
            error_code = 1
            info = "request data error, {}".format(e)
            res = {
                "error_code": error_code,
                "info": '',
                "session_id": ""
            }
            logger.info(info)
            return jsonify(res)

    def start_market_dynamics_labeling(self, request):
        request_json = json.loads(request.get_data(as_text=True))
        try:
            # get input args

            info=''
            # market_dynamics_labeling parameters
            args = {}
            args['dataset_name'] = request_json.get("dataset_name")
            args['number_of_market_dynamics'] = request_json.get("number_of_market_style")
            if int(args['number_of_market_dynamics']) not in [3, 4]:
                raise Exception('We only support dynamics number of 3 or 4 for now')
            args['minimun_length'] = request_json.get("length_time_slice")
            args['Granularity'] = request_json.get("granularity")
            args['bear_threshold'] = request_json.get("bear_threshold")
            args['bull_threshold'] = request_json.get("bull_threshold")

            try:
                session_id = request_json.get("session_id")
            except:
                # if no session_id, create a new session with fake_training
                session_id = self.fake_training(dataset_name=args['dataset_name'])
            # load session
            self.sessions = self.load_sessions()
            if session_id in self.sessions:
                work_dir = self.sessions[session_id]["work_dir"]
                cfg_path = self.sessions[session_id]["cfg_path"]
                custom_datafile_paths = self.sessions[session_id]["custom_datafile_paths"]
                # parse all custom data file name from custom_datafile_paths
                custom_datafile_names = [os.path.basename(path).split('.')[0] for path in custom_datafile_paths]
            # prepare data

            cfg = Config.fromfile(cfg_path)
            cfg = replace_cfg_vals(cfg)
            test_start_date = request_json.get("evaluation_start_date")
            test_end_date = request_json.get("evaluation_end_date")
            # test_start_date = "2010-01-01"
            # test_end_date = "2015-01-01"

            # if dataset is custom, change the cfg.data.data_path to custom data path
            if args['dataset_name'] in custom_datafile_names:
                cfg.data.data_path = custom_datafile_paths[custom_datafile_names.index(args['dataset_name'])]

            data = pd.read_csv(os.path.join(ROOT, cfg.data.data_path, "data.csv"), index_col=0)


            data = data[(data["date"] >= test_start_date) & (data["date"] < test_end_date)]
            info += f"There are total {data.shape[0]} ticks in the dataset\\n"
            data_path = os.path.join(work_dir, "dynamics_test.csv").replace("\\", "/")
            data.to_csv(data_path)
            args['dataset_path'] = data_path

            # prepare PM index data if needed
            if request_json.get("dataset_name") == 'portfolio_management:dj30':
                DJI_data = pd.read_csv(os.path.join(ROOT, cfg.data.data_path, "DJI.csv"), index_col=0)
                DJI_data = DJI_data[(DJI_data["date"] >= test_start_date) & (DJI_data["date"] < test_end_date)]
                DJI_data_path = os.path.join(work_dir, "DJI_index_dynamics_test.csv").replace("\\", "/")
                DJI_data.to_csv(DJI_data_path)
                args['PM'] = args['dataset_path']
                args['dataset_path']=DJI_data_path
            else:
                args['PM'] = ''


            # update MDM cfg

            MDM_cfg_path = os.path.join(ROOT, "configs", 'evaluation',
                                        f"market_dynamics_modeling.py")

            MDM_cfg = Config.fromfile(MDM_cfg_path)
            MDM_cfg = replace_cfg_vals(MDM_cfg)
            # front-end args to back-end args
            args = MRL_F2B_args_converter(args)
            MDM_cfg.market_dynamics_model.update({'data_path': args['data_path'],
                                                  'fitting_parameters': args['fitting_parameters'],
                                                  'slope_interval': args['slope_interval'],
                                                  'dynamic_number': args['dynamic_number'],
                                                  'max_length_expectation': args['max_length_expectation'],
                                                  'OE_BTC': args['OE_BTC'],
                                                  'PM': args['PM']
                                                  })
            MDM_cfg_path = os.path.join(work_dir, osp.basename(MDM_cfg_path))
            MDM_cfg.dump(MDM_cfg_path)
            logger.info(MDM_cfg)
            MDM_log_path = os.path.join(work_dir, "MDM_log.txt")
            MDM_script_path = self.train_scripts('market_dynamics_modeling', '', '', '', '')
            MDM_dataset_name = args['dataset_name']

            # update session file

            # first test
            if "MDM_cfg_path" not in self.sessions[session_id]:
                self.sessions = self.dump_sessions({session_id: self.sessions[session_id] | {
                    "MDM_cfg_path": MDM_cfg_path,
                    "MDM_script_path": MDM_script_path,
                    "MDM_log_path": MDM_log_path,
                    "MDM_dataset_name": MDM_dataset_name
                }})
            # following dump
            else:
                self.sessions[session_id]["MDM_cfg_path"] = MDM_cfg_path
                self.sessions[session_id]["MDM_script_path"] = MDM_script_path
                self.sessions[session_id]["MDM_log_path"] = MDM_log_path
                self.sessions[session_id]["MDM_dataset_name"] = MDM_dataset_name
                self.sessions = self.dump_sessions({session_id: self.sessions[session_id]})

            # run MDM
            cmd = "conda activate TradeMaster && nohup python -u {} --config {} > {} 2>&1 &".format(
                MDM_script_path,
                MDM_cfg_path,
                MDM_log_path)
            logger.info(cmd)
            MDM_run_info = run_cmd(cmd)
            logger.info(MDM_run_info)

            # reload MDM_cfg to get results
            MDM_cfg = Config.fromfile(MDM_cfg_path)
            MDM_cfg = replace_cfg_vals(MDM_cfg)
            MDM_datafile_path = MDM_cfg.market_dynamics_model.process_datafile_path
            MDM_visualization_paths = MDM_cfg.market_dynamics_model.market_dynamic_labeling_visualization_paths

            with open(MDM_visualization_paths[0], "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read())

            # update session information:
            if "MDM_datafile_path" not in self.sessions[session_id]:
                self.sessions[session_id]["MDM_cfg_path"] = MDM_cfg_path
                self.sessions[session_id]["MDM_script_path"] = MDM_script_path
                self.sessions[session_id]["MDM_log_path"] = MDM_log_path
                self.sessions[session_id]["MDM_dataset_name"] = MDM_dataset_name
                self.sessions = self.dump_sessions({session_id: self.sessions[session_id] |
                                                                {
                                                                    "MDM_datafile_path": MDM_datafile_path,
                                                                    "MDM_visualization_paths": MDM_visualization_paths}
                                                    })
            else:
                self.sessions[session_id]["MDM_cfg_path"] = MDM_cfg_path
                self.sessions[session_id]["MDM_script_path"] = MDM_script_path
                self.sessions[session_id]["MDM_log_path"] = MDM_log_path
                self.sessions[session_id]["MDM_datafile_path"] = MDM_datafile_path
                self.sessions[session_id]["MDM_visualization_paths"] = MDM_visualization_paths
                self.sessions[session_id]["MDM_dataset_name"] = MDM_dataset_name
                self.sessions = self.dump_sessions({session_id: self.sessions[session_id]})

            error_code = 0
            info = "request success, show market dynamics labeling visualization" + info

            res = {
                "error_code": error_code,
                "info": info,
                "market_dynamic_labeling_visulization": str(encoded_string, 'utf-8'),
                "session_id": session_id
            }
            logger.info(info)
            return jsonify(res)

        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            error_code = 1
            info = "request data error, {}".format(e)
            res = {
                "error_code": error_code,
                "info": info + str(exc_type) + str(fname) + str(exc_tb.tb_lineno),
                "market_dynamic_labeling_visulization": "",
                "session_id": session_id
            }
            logger.info(info)
            return jsonify(res)

    def save_market_dynamics_labeling(self, request):
        request_json = json.loads(request.get_data(as_text=True))
        try:
            session_id = request_json.get("session_id")

            self.sessions = self.load_sessions()
            if session_id in self.sessions:
                work_dir = self.sessions[session_id]["work_dir"]
                cfg_path = self.sessions[session_id]["cfg_path"]
                MDM_datafile_path = self.sessions[session_id]["MDM_datafile_path"]
                MDM_dataset_name = self.sessions[session_id]["MDM_dataset_name"]

            cfg = Config.fromfile(cfg_path)
            cfg = replace_cfg_vals(cfg)

            # update dataset cfg
            cfg.data.test_dynamic_path = MDM_datafile_path.replace("\\", "/")
            cfg_path = os.path.join(work_dir, osp.basename(cfg_path))
            cfg.dump(cfg_path)
            logger.info(cfg)
            error_code = 0
            info = "request success, save market dynamics"
            res = {
                "error_code": error_code,
                "info": info
            }
            logger.info(info)
            return jsonify(res)

        except Exception as e:
            error_code = 1
            info = "request data error, {}".format(e)
            res = {
                "error_code": error_code,
                "info": info
            }
            logger.info(info)
            return jsonify(res)

    def run_dynamics_test(self, request):
        request_json = json.loads(request.get_data(as_text=True))
        try:
            dynamics_test_label = request_json.get("0")
            session_id = request_json.get("session_id")
            logger.info(request_json)

            self.sessions = self.load_sessions()
            addtional_info = ''
            if session_id in self.sessions:
                work_dir = self.sessions[session_id]["work_dir"]
                cfg_path = self.sessions[session_id]["cfg_path"]
                train_script_path = self.sessions[session_id]["script_path"]
                task_name = self.sessions[session_id]["task_name"]
            cfg = Config.fromfile(cfg_path)
            cfg = replace_cfg_vals(cfg)
            cfg_path = os.path.join(work_dir, osp.basename(cfg_path))
            dt_log_path = os.path.join(work_dir, "dynamics_test_" + str(dynamics_test_label) + "_log.txt")
            cmd = "conda activate TradeMaster && nohup python -u {} --config {} --task_name dynamics_test --test_dynamic {} > {} 2>&1 &".format(
                train_script_path,
                cfg_path,
                dynamics_test_label,
                dt_log_path)
            logger.info(cmd)
            DT_info = run_cmd(cmd)
            logger.info(DT_info)
            radar_plot_path = osp.join(work_dir, 'radar_plot_agent_' + str(dynamics_test_label) + '.png')
            if task_name == "order_execution":
                encoded_string = ""
                addtional_info += '\n we do not provide radar report for order execution task for now'
            else:
                with open(radar_plot_path, "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read())

            # print log output
            print_log_cmd = "tail -n 100 {}".format(dt_log_path)
            dynamics_test_log_info = run_cmd(print_log_cmd)

            error_code = 0
            info = f"request success, start test market {dynamics_test_label}\n\n"
            res = {
                "error_code": error_code,
                "info": info + dynamics_test_log_info + addtional_info,
                "session_id": session_id,
                'radar_plot': str(encoded_string, 'utf-8')
            }
            logger.info(info)
            return jsonify(res)

        except Exception as e:
            error_code = 1
            info = "request data error, {}".format(e)
            res = {
                "error_code": error_code,
                "info": info,
                "session_id": "",
                'radar_plot': ""
            }
            logger.info(info)
            return jsonify(res)


    def upload_csv(self, request):
        request_json = json.loads(request.get_data(as_text=True))
        try:
            uploaded_file = request_json.get('file')
            if uploaded_file.filename == '':
                return jsonify({'error': 'No file selected'}), 400

            if uploaded_file and uploaded_file.filename.endswith('.csv'):
                file_data = uploaded_file.stream.read().decode("utf-8")
                #get file name without extension
                custom_data_name = uploaded_file.filename.split('.')[0]
                custom_data = list(csv.reader(file_data.splitlines()))


            try:
                session_id = request_json.get("session_id")
            except:
                # if session_id is not provided, create a new session with fake_training()
                session_id = self.fake_training(dataset_name=custom_data_name)
                # create new session
                # we will use a default cfg file because we will not actually run an agent in this use case
                # cfg_path = os.path.join(ROOT, "configs", 'algorithmic_trading',
                #                         'algorithmic_trading_BTC_deepscalper_deepscalper_adam_mse.py')
                # # train_script_path = self.train_scripts(task_name, dataset_name, optimizer_name, loss_name, agent_name)
                # work_dir = os.path.join(ROOT, "work_dir", session_id,
                #                         f"dynamic_labeling_{args['dataset_name']}")
                # if not os.path.exists(work_dir):
                #     os.makedirs(work_dir)
                #
                # cfg = Config.fromfile(cfg_path)
                # cfg = replace_cfg_vals(cfg)
                # cfg.work_dir = "work_dir/{}/{}".format(session_id,
                #                                        'dynamic_labeling_{}'.format(args['dataset_name']))
                # cfg.trainer.work_dir = cfg.work_dir





            # if 'file' not in request_json.files:
            #     return jsonify({'error': 'No file found in request'}), 400

            # uploaded_file = request_json.get('file')
            # if uploaded_file.filename == '':
            #     return jsonify({'error': 'No file selected'}), 400
            #
            # if uploaded_file and uploaded_file.filename.endswith('.csv'):
            #     file_data = uploaded_file.stream.read().decode("utf-8")
            #     #get file name without extension
            #     custom_data_name = uploaded_file.filename.split('.')[0]
            #     custom_data = list(csv.reader(file_data.splitlines()))
                # return jsonify(csv_data)

            self.sessions = self.load_sessions()
            if session_id in self.sessions:
                work_dir = self.sessions[session_id]["work_dir"]
            # save custom data to csv file in work_dir
            custom_datafile_path = os.path.join(work_dir, custom_data_name + ".csv")
            with open(custom_datafile_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerows(custom_data)

            # update session info
            if "custom_datafile_paths" not in self.sessions[session_id]:
                self.sessions[session_id]["custom_datafile_paths"] = [custom_datafile_path]
                self.sessions = self.dump_sessions({session_id: self.sessions[session_id] |
                                                                {
                                                                    "custom_datafile_paths":[custom_datafile_path],}
                                                    })
            else:
                self.sessions[session_id]["custom_datafile_paths"].append(custom_datafile_path)
                self.sessions = self.dump_sessions({session_id: self.sessions[session_id]})



            error_code = 0
            info = "request success, read uploaded csv file"
            res = {
                "error_code": error_code,
                "info": info,
                "session_id": session_id
            }
            logger.info(info)
            return jsonify(res)

        except Exception as e:
            error_code = 1
            info = "request error, {}".format(e)
            res = {
                "error_code": error_code,
                "info": info,
                "session_id": session_id
            }
            logger.info(info)
            return jsonify(res)


    def fake_training(self,task_name = "algorithmic_trading",
        dataset_name = "algorithmic_trading:BTC".split(":")[-1],
        optimizer_name = "adam",
        loss_name = "mse",
        agent_name = "algorithmic_trading:deepscalper".split(":")[-1],
        start_date = "2015-10-01",
        end_date = "2021-07-06"):

        task_name = task_name
        dataset_name = dataset_name
        optimizer_name = optimizer_name
        loss_name = loss_name
        agent_name = agent_name
        start_date = start_date
        end_date = end_date
        ##TODO
        session_id = str(uuid.uuid1())

        cfg_path = os.path.join(ROOT, "configs", task_name,
                                f"{task_name}_algorithmic_trading_{agent_name}_{agent_name}_{optimizer_name}_{loss_name}.py")
        train_script_path = self.train_scripts(task_name, "algorithmic_trading", optimizer_name, loss_name, agent_name)
        work_dir = os.path.join(ROOT, "work_dir", session_id,
                                'dynamic_labeling')
        if not os.path.exists(work_dir):
            os.makedirs(work_dir)

        cfg = Config.fromfile(cfg_path)
        cfg = replace_cfg_vals(cfg)
        cfg.work_dir = "work_dir/{}/{}".format(session_id,
                                               'dynamic_labeling')
        cfg.trainer.work_dir = cfg.work_dir

        # # build dataset
        # data = pd.read_csv(os.path.join(ROOT, cfg.data.data_path, "data.csv"), index_col=0)
        # data = data[(data["date"] >= start_date) & (data["date"] < end_date)]
        #
        # # indexs = range(len(data.index.unique()))
        # indexs = data.index.unique()
        #
        # train_indexs = indexs[:int(len(indexs) * 0.8)]
        # val_indexs = indexs[int(len(indexs) * 0.8):int(len(indexs) * 0.9)]
        # test_indexs = indexs[int(len(indexs) * 0.9):]
        #
        # train_data = data.loc[train_indexs, :]
        # train_data.index = train_data.index - train_data.index.min()
        #
        # val_data = data.loc[val_indexs, :]
        # val_data.index = val_data.index - val_data.index.min()
        #
        # test_data = data.loc[test_indexs, :]
        # test_data.index = test_data.index - test_data.index.min()
        #
        # train_data.to_csv(os.path.join(work_dir, "train.csv"))
        cfg.data.train_path = "{}/{}".format(cfg.work_dir, "train.csv")
        # val_data.to_csv(os.path.join(work_dir, "valid.csv"))
        cfg.data.valid_path = "{}/{}".format(cfg.work_dir, "valid.csv")
        # test_data.to_csv(os.path.join(work_dir, "test.csv"))
        cfg.data.test_path = "{}/{}".format(cfg.work_dir, "test.csv")

        cfg_path = os.path.join(work_dir, osp.basename(cfg_path))
        cfg.dump(cfg_path)
        logger.info(cfg)

        log_path = os.path.join(work_dir, "train_log.txt")

        self.sessions = self.dump_sessions({session_id: {
            "dataset": dataset_name,
            "task_name": task_name,
            "work_dir": work_dir,
            "cfg_path": cfg_path,
            "script_path": train_script_path,
            "train_log_path": log_path,
            "test_log_path": os.path.join(os.path.dirname(log_path), "test_log.txt")
        }})

        return session_id
        # cmd = "conda activate TradeMaster && nohup python -u {} --config {} --task_name train > {} 2>&1 &".format(
        #     train_script_path,
        #     cfg_path,
        #     log_path)
        #
        # executor.submit(run_cmd, cmd)
        # logger.info(cmd)

        # error_code = 0
        # info = "request success, start train"
        # res = {
        #     "error_code": error_code,
        #     "info": info,
        #     "session_id": session_id
        # }
        # logger.info(info)
        # return jsonify(res)


    def download_csv(self, request):
        request_json = json.loads(request.get_data(as_text=True))
        try:
            session_id = request_json.get("session_id")

            self.sessions = self.load_sessions()
            if session_id in self.sessions:
                work_dir = self.sessions[session_id]["work_dir"]
                # get the saved csv file path that is set in save_market_dynamics_labeling()
                # TODO: modify the save_market_dynamics_labeling()
                # get all custom data file paths
                custom_datafile_paths = self.sessions[session_id]["custom_datafile_paths"]
                MDM_dataset_name = self.sessions[session_id]["MDM_dataset_name"]

            # parse all custom data file name from custom_datafile_paths
            custom_datafile_names = [os.path.basename(path).split('.')[0] for path in custom_datafile_paths]

            # forbid download csv file if it is not a custom data
            if MDM_dataset_name not in custom_datafile_names:
                error_code = 1
                info = "request error, you can only download custom data"
                res = {
                    "error_code": error_code,
                    "info": info,
                    "file": None
                }
                logger.info(info)
                return jsonify(res)

            # get the saved csv file path that is set in save_market_dynamics_labeling()
            saved_dataset_path = os.path.join(work_dir, MDM_dataset_name + ".csv")

            # Read the CSV file contents
            with open(saved_dataset_path, 'r', encoding='utf-8') as file:
                csv_data = file.read()

            # Create a response with appropriate headers for downloading a CSV file
            response = Response(
                csv_data,
                content_type='text/csv',
                headers={
                    "Content-Disposition": f"attachment; filename={MDM_dataset_name}",
                    "Content-Type": "text/csv; charset=utf-8"
                }
            )

            error_code = 0
            info = "request success, read uploaded csv file"
            res = {
                "error_code": error_code,
                "info": info,
                "file": response
            }
            logger.info(info)
            return jsonify(res)

        except Exception as e:
            error_code = 1
            info = "request error, {}".format(e)
            res = {
                "error_code": error_code,
                "info": info,
                "file": None
            }
            logger.info(info)
            return jsonify(res)


class HealthCheck():
    def __init__(self):
        super(HealthCheck, self).__init__()

    def run(self, request):
        start = time.time()
        if request.method == "GET":
            logger.info("health check start.")
            error_code = 0
            info = "health check"
            time_consuming = (time.time() - start) * 1000
            res = {
                "data": {},
                "error_code": error_code,
                "info": info,
                "time_consuming": time_consuming
            }
            logger.info("health check end.")
            return jsonify(res)


SERVER = Server()
HEALTHCHECK = HealthCheck()

@app.route("/api/TradeMaster/upload_csv", methods=['POST'])
def upload_csv():
    res = SERVER.upload_csv(request)
    return res

@app.route("/api/TradeMaster/download_csv", methods=['POST'])
def download_csv():
    res = SERVER.download_csv(request)
    return res

@app.route("/api/TradeMaster/getParameters", methods=["GET"])
def getParameters():
    res = SERVER.get_parameters(request)
    return res

@app.route("/api/TradeMaster/evaluation_getParameters", methods=["GET"])
def evaluation_getParameters():
    res = SERVER.evaluation_parameters()
    return res


@app.route("/api/TradeMaster/train", methods=["POST"])
def train():
    res = SERVER.train(request)
    return res


@app.route("/api/TradeMaster/train_status", methods=["POST"])
def train_status():
    res = SERVER.train_status(request)
    return res


@app.route("/api/TradeMaster/test", methods=["POST"])
def test():
    res = SERVER.test(request)
    return res


@app.route("/api/TradeMaster/test_status", methods=["POST"])
def test_status():
    res = SERVER.test_status(request)
    return res


@app.route("/api/TradeMaster/start_market_dynamics_labeling", methods=["POST"])
def start_market_dynamics_labeling():
    res = SERVER.start_market_dynamics_labeling(request)
    return res


@app.route("/api/TradeMaster/save_market_dynamics_labeling", methods=["POST"])
def save_market_dynamics_labeling():
    res = SERVER.save_market_dynamics_labeling(request)
    return res


@app.route("/api/TradeMaster/run_dynamics_test", methods=["POST"])
def run_style_test():
    res = SERVER.run_dynamics_test(request)
    return res


@app.route("/api/TradeMaster/healthcheck", methods=["GET"])
def health_check():
    res = HEALTHCHECK.run(request)
    return res


if __name__ == "__main__":
    host = "127.0.0.1"
    port = 8080
    app.run(host, port)
