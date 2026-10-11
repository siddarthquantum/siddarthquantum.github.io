import java.util.ArrayList;
import java.util.List;

public class CustomerData {
    //1. Class variabe
    private String name;
    private Double salary;
    //2. Constractor
    public CustomerData(String name, Double salary){
        this.name = name;
        this.salary = salary;
    }
    //3. Getters
    public String getName(){
        return this.name;
    }

    public Double getSalary(){
        return this.salary;
    }

    public static void main(String args[]){

    List<CustomerData> customerList = new ArrayList<>();
    CustomerData custObj1 = new CustomerData("siddar", 343.6);
    
    customerList.add(custObj1);
    customerList.add(new CustomerData("moshan", 5656.78));
    customerList.add(new CustomerData("diya", 5856.78));
    customerList.add(new CustomerData("jiya", 1656.78));
    customerList.add(new CustomerData("maya", 1656.78));
    
    for(CustomerData custmer : customerList) {
        System.out.println(custmer.getName());
        System.out.println(custmer.getSalary());
        
    }
    double maxSalaray = 0.0;
    for(CustomerData customerData:customerList){
        if(customerData.getSalary() > maxSalaray){
            maxSalaray = customerData.getSalary();
        }
    }
    System.out.println("The higesht salary "+maxSalaray);
    }

} 