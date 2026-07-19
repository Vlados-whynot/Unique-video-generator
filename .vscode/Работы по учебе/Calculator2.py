while True:
    try:
        num1=float(input("Введите первое число:"))
    except ValueError:
        print("Ошибка: введите корректное число!")
        continue
    operation=input("Выберите операцию(+, -, *, /) или 'q' для выхода")
    if operation.lower()=='q':
       print("До свидания!")
       break

    try:
        num2=float(input("Введите второе число!"))
    except ValueError:
        print("Ошибка: введите корректное число!")
        continue
    if operation=="+":
       result=num1+num2
    elif operation=="-":
       result=num1-num2
    elif operation=="*":
       result=num1*num2
    elif operation=="/":
       if num2 !=0:
          result=num1/num2
       else:
            result="Ошибка: деление на ноль!"
    else:
        result="Ошибка: неверная операция!"
    print(f"Результат:{result}\n")       