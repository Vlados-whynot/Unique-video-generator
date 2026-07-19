num1=float(input("Введите первое число!")) #запрашиваем первое число 
operation=input("Выберите операцию (+, -, *, /): ") #запрашивает опирацию
num2=float(input("Введите второе число!")) #запрашивает второе число
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
    result="Ошибка: неверная опирация!"
print(f"Результат:{result}")