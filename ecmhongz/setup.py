from setuptools import setup, find_packages

setup(
    name="ecmhongz",  
    version="0.2.0",  
    author="HongzhenHuang",
    author_email="202130500072@mail.scut.edn.cn", 
    description="ecmhong is a Python package for Energy Consumption Monitoring created by HongzhenHuang.",  # 简短描述
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/SusCom-Lab/ECM-Tool",  # 你的项目主页
    install_requires=[
        "psutil",
        "mysql-connector-python",  
        "pandas",
        "plotly",
        "deprecated",
        "numpy",
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.7",  # 适用的 Python 版本
)
