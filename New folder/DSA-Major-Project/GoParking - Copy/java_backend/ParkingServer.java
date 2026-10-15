import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.PrintWriter;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.ArrayList;

public class ParkingServer {

    private static final int PORT = 5000;
    private static final ParkingLot parkingLot = new ParkingLot(10);

    public static void main(String[] args) {

        System.out.println("GoParking Java Server starting...");

        try (ServerSocket serverSocket = new ServerSocket(PORT)) {

            System.out.println("Server running on port " + PORT);

            while (true) {
                try (
                    Socket client = serverSocket.accept();
                    BufferedReader in = new BufferedReader(
                        new InputStreamReader(client.getInputStream()));
                    PrintWriter out = new PrintWriter(
                        client.getOutputStream(), true)
                ) {
                    String request = in.readLine();

                    if (request == null || request.trim().isEmpty()) {
                        out.println("ERROR|Empty request");
                        continue;
                    }

                    out.println(handleCommand(request.trim()));

                } catch (Exception e) {
                    System.err.println(
                        "Request error: " + e.getMessage());
                }
            }

        } catch (Exception e) {
            System.err.println(
                "Server error: " + e.getMessage());
        }
    }

    private static synchronized String handleCommand(String request) {

        try {
            String[] parts = request.split("\\|", -1);
            String command = parts[0].trim().toUpperCase();

            switch (command) {

                case "PARK": {
                    if (parts.length != 4) {
                        return "ERROR|Use PARK|registration|color|type";
                    }

                    String reg = parts[1].trim().toUpperCase();
                    String color = parts[2].trim();
                    String type = parts[3].trim();

                    if (reg.isEmpty() || color.isEmpty()
                            || type.isEmpty()) {
                        return "ERROR|All vehicle fields are required";
                    }

                    return parkingLot.parkVehicle(
                        new Vehicle(reg, color, type));
                }

                case "REMOVE": {
                    if (parts.length != 2) {
                        return "ERROR|Use REMOVE|registration";
                    }

                    return parkingLot.removeVehicle(parts[1]);
                }

                case "FIND": {
                    if (parts.length != 2) {
                        return "ERROR|Use FIND|registration";
                    }

                    return parkingLot.findVehicle(parts[1]);
                }

                case "COLOR": {
                    if (parts.length != 2) {
                        return "ERROR|Use COLOR|color";
                    }

                    return parkingLot.findVehiclesByColor(parts[1]);
                }

                case "STATUS": {
                    return parkingLot.getStatus();
                }

                case "SLOTS": {
                    return parkingLot.getAllParkingSlots();
                }

                case "HISTORY": {
                    ArrayList<ParkingHistory> history =
                        parkingLot.getParkingHistory();

                    StringBuilder result =
                        new StringBuilder("HISTORY");

                    for (ParkingHistory h : history) {
                        result.append("|")
                              .append(h.getRegistrationNumber())
                              .append("|")
                              .append(h.getColor())
                              .append("|")
                              .append(h.getVehicleType())
                              .append("|")
                              .append(h.getSlotNumber())
                              .append("|")
                              .append(h.getFormattedEntryTime())
                              .append("|")
                              .append(h.getFormattedExitTime());
                    }

                    return result.toString();
                }

                case "RESTORE": {
                    if (parts.length != 5) {
                        return "ERROR|Use RESTORE|registration|color|type|slot";
                    }

                    String reg = parts[1].trim().toUpperCase();
                    String color = parts[2].trim();
                    String type = parts[3].trim();
                    int slotNumber;

                    try {
                        slotNumber = Integer.parseInt(parts[4].trim());
                    } catch (NumberFormatException e) {
                        return "ERROR|Invalid slot number";
                    }

                    boolean restored = parkingLot.restoreVehicle(
                        reg, color, type, slotNumber);

                    if (restored) {
                        return "OK|Vehicle restored|" + reg
                            + "|" + color + "|" + type
                            + "|" + slotNumber;
                    }

                    return "ERROR|Restore failed|Vehicle may already exist or slot is unavailable";
                }

                default:
                    return "ERROR|Unknown command";
            }

        } catch (Exception e) {
            return "ERROR|Request failed: " + e.getMessage();
        }
    }
}