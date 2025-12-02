## Auto Test framework v3.0
> API & UI Auto Test framework by using python language + pytest + allure 

English | [简体中文](./README.md)

- A Simple architecture diagram

![IsXMnO.png](./1.png)


## function realized
- Interface data dependency: interface B can use a field in interface a's response as a parameter
- Dynamic multiple assertions: multiple assertions that dynamically extract the actual expected results and compare them with the specified expected results
- Support SQL query assertions
- Support the writing of UI test cases based on the PO model
- Rewrite the source code of the page and context methods, supporting session persistence
- Automatically update the status of online test cases upon test completion, such as: passed, failed, skipped...
- Generate an allure style report when the test has complete.
## dependency
```
allure-pytest==2.8.17		
jsonpath==0.82				
loguru==0.5.1				
pytest==6.0.1				
PyYAML==5.3.1				
requests==2.24.0			
xlrd==1.2.0					
xlwt==1.3.0                 
```
## directory structure
```shell
├─config
│  └─config.yaml	# the config
├─log
│  └─YYYY-MM-DD.log	# the log file, end-with YYYY-MM-DD.log
├─page
  └─home.py	# UI layer base encapsulation
├─recordings	# The location where the recording steps are stored can be referred to by the AI based on the elements here.
├─report
│  ├─data           # allure test report data
│  └─html			# allure test report
   └─video			# allure test report
├─test-result       # Test output path of screen recording and screenshot results
├─test_case
|  └─UI
|    ├─conftest.py  # UI test initialization
|    ├─test_case.yaml # UI test case, preparation method see the document description
│    └─test_ui.py	  # Test method
├─tools		            
│  ├─__init__.py		# the common test function
│  ├─data_process.py	# the data process
|  ├─sql_operate.py   # Database operation
|  ├─email_send.py    # Mail sending
|  ├─encode.py        # Interface encryption and decryption
|  ├─generate_data.py # Test data generation
|  ├─read_file.py     # yaml file gets wrapped
|  └─get_cookie.py    # Get login cookie
|  └─update_test_status.py    # Update the status of the online test cases
├─requirements.txt		 # dependency file
└─main.py	# the main file to start the project
```

## how to start
1. install the dependecy by using pip install -r requirements.txt
```shell
注：If the target server to be migrated cannot be networked, you can download the dependent packages to the packages/ folder of the current directory by using the command of pip download -d packages/ -r requirements.txt , and then the target server can use the command of pip install --no-index --find-links=packages/ -r requirements.txt to offline install dependent package
```
2. write the case
```shell
#UI test case writing guide
#Write as follows to drive test execution with keywords
#Use case names are recommended for easy management and neat appearance, for example, xxx(project)-xxx(mudule)-test001
#descrption(Use case description)
#test_step(Test step) Writing sample test_step: {"open": "https://www.jd.com/",
#"click1": "id=msShortcutLogin",
#"fill1": {"selector": "#sb_form_q", "value": "test_account20221212"},
#"swipe": {"x": 500, y: 800}
#"sleep": 3000
#}
#Supported keywords are open(open url), click1(click event,1 represents the first click, similarly click2 represents the second click in the test case)
#sleep(explicit wait, milliseconds),fill1(text fill event, passing in two key-value pairs, a filled element object and a filled value. The number 1 is used in the same way as click1)
#swipe(page swipe event)
#expect_result Writing sample {"descrption": "expected page "#header &gt; Spn.text-header "The copy of the element is' Beijing login registration '",
#"selector": "#header &gt;  span.text-header",
#"value": "JD login Registration"
#}
```
3. start test by the command python main.py
4. see the report and result

